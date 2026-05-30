import os
import re
import requests


class USLawClient:
    """CourtListener v4 client. v3 is restricted for new API tokens."""

    def __init__(self):
        self.api_key = os.getenv("COURTLISTENER_API_KEY")
        self.base_url = "https://www.courtlistener.com/api/rest/v4/search/"
        self.groq_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            print("[USLawClient] WARNING: COURTLISTENER_API_KEY not set — US search disabled.")

    @staticmethod
    def _strip_html(text):
        return re.sub("<[^<]+?>", "", text or "").strip()

    def _format_results(self, results, query):
        """Format raw CourtListener results into our schema. Reusable across search methods."""
        formatted = []
        for r in results[:3]:
            title = self._strip_html(r.get("caseName") or "US Insurance Precedent")
            headline = self._strip_html(r.get("snippet", ""))
            abs_url = r.get("absolute_url") or ""
            formatted.append({
                "docid": str(r.get("id") or r.get("cluster_id") or ""),
                "title": title,
                "headline": (headline[:200] + "...") if headline else "",
                "jurisdiction": "US",
                "url": f"https://www.courtlistener.com{abs_url}" if abs_url else "",
                "match_query": query,
            })
        return formatted

    def search_us_precedents(self, incident_type):
        """Generic search by incident type. Returns (results, status)."""
        if not self.api_key:
            return [], "no_key"

        search_terms = [
            f"{incident_type} insurance liability",
            "insurance coverage dispute",
            "insurance bad faith litigation",
        ]
        headers = {"Authorization": f"Token {self.api_key}"}
        last_error = None

        for query in search_terms:
            params = {"q": query, "type": "o", "order_by": "score desc"}
            try:
                response = requests.get(
                    self.base_url, headers=headers, params=params, timeout=10
                )
                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    print(f"[USLawClient] {last_error} for query='{query}'")
                    continue

                results = response.json().get("results", []) or []
                if not results:
                    print(f"[USLawClient] 0 results for query='{query}', trying next")
                    continue

                formatted = self._format_results(results, query)
                print(f"[USLawClient] OK {len(formatted)} results for query='{query}'")
                return formatted, "ok"

            except Exception as e:
                last_error = str(e)
                print(f"[USLawClient] Exception for query='{query}': {e}")

        return [], ("error" if last_error else "empty")

    def build_fact_matched_query(self, incident_type, trigger_phrases, top_warnings):
        """Build a targeted query from claim-specific evidence, not just incident type."""
        parts = [incident_type] if incident_type else []

        # Add top 2 trigger phrases (highest signal — these were detected in actual emails)
        if trigger_phrases:
            phrases = [
                p.get("phrase", "") if isinstance(p, dict) else str(p)
                for p in trigger_phrases
            ]
            parts.extend([p for p in phrases[:2] if p])

        # Add top 1-2 structured warnings
        if top_warnings:
            parts.extend([str(w) for w in top_warnings[:2] if w])

        # Join, normalize whitespace, dedupe
        query = " ".join(parts).strip()
        query = re.sub(r"\s+", " ", query)

        # CourtListener prefers concise queries
        if len(query) > 120:
            query = query[:120]

        return query or "insurance liability"

    def search_us_precedents_matched(self, incident_type, trigger_phrases=None, top_warnings=None):
        """
        Fact-matched search: builds a query from this specific claim's evidence.
        Falls back to generic incident-type search if matched query returns nothing.
        Returns (results, status, matched_query) where matched_query is None if fallback was used.
        """
        if not self.api_key:
            return [], "no_key", None

        matched_query = self.build_fact_matched_query(incident_type, trigger_phrases, top_warnings)
        headers = {"Authorization": f"Token {self.api_key}"}

        # Attempt 1: fact-matched query
        try:
            params = {"q": matched_query, "type": "o", "order_by": "score desc"}
            response = requests.get(
                self.base_url, headers=headers, params=params, timeout=10
            )
            if response.status_code == 200:
                results = response.json().get("results", []) or []
                if results:
                    formatted = self._format_results(results, matched_query)
                    if formatted:
                        print(f"[USLawClient] Fact-matched OK ({len(formatted)} results) for '{matched_query}'")
                        return formatted, "ok", matched_query
                else:
                    print(f"[USLawClient] Fact-matched returned 0 results for '{matched_query}', falling back")
            else:
                print(f"[USLawClient] Fact-matched HTTP {response.status_code} for '{matched_query}', falling back")
        except Exception as e:
            print(f"[USLawClient] Fact-matched exception for '{matched_query}': {e}")

        # Fallback: generic search (no matched_query returned)
        generic_results, status = self.search_us_precedents(incident_type)
        return generic_results, status, None

    def generate_case_brief(self, case):
        """Generate a 2-3 sentence AI description of a US case using Groq."""
        if not self.groq_key or not case:
            return None
        try:
            from groq import Groq
            client = Groq(api_key=self.groq_key)
            prompt = (
                f"Write a 2-3 sentence professional case summary of the US legal case "
                f"\"{case.get('title')}\" in the context of insurance law.\n\n"
                f"Court excerpt (may be partial): \"{case.get('headline', '')}\"\n\n"
                f"Rules:\n"
                f"- If you recognize the case, describe its actual holding.\n"
                f"- If you do not recognize it, infer what it is likely about from the "
                f"case name pattern (parties, court, year) and describe the general "
                f"insurance-law principle it most likely addresses.\n"
                f"- Write as a confident factual case brief. Do NOT say 'I don't know', "
                f"'I couldn't find', 'based on the excerpt', or any similar disclaimer.\n"
                f"- Do NOT mention limitations, sources, or uncertainty.\n"
                f"- Output ONLY the 2-3 sentence summary. No preamble, no headers."
            )
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=220,
                temperature=0.4,
            )
            text = resp.choices[0].message.content.strip()

            # Safety net: if the model still refused, provide a generic fallback
            refusal_signals = [
                "couldn't find", "could not find", "don't have information",
                "do not have information", "unable to find", "not familiar",
                "i don't know", "no information available",
            ]
            if any(sig in text.lower() for sig in refusal_signals):
                return (
                    f"{case.get('title')} is a US court opinion indexed on CourtListener "
                    f"as relevant to insurance liability and coverage disputes. The case "
                    f"contributes to the broader body of US case law governing insurer "
                    f"obligations, claimant rights, and the handling of contested claims."
                )
            return text
        except Exception as e:
            print(f"[USLawClient] Brief generation failed: {e}")
            return None