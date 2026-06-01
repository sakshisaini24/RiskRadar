import os
import re
import requests

API_ROOT = "https://www.courtlistener.com/api/rest/v4"
MAX_EXCERPT_CHARS = 1800

HEDGING_WORDS = re.compile(
    r"\b(likely|probably|may have|might have|possibly|appears to|seems to|"
    r"it is possible|could be|may be)\b",
    re.IGNORECASE,
)


class USLawClient:
    """CourtListener v4 client. v3 is restricted for new API tokens."""

    def __init__(self):
        self.api_key = os.getenv("COURTLISTENER_API_KEY")
        self.base_url = f"{API_ROOT}/search/"
        self.groq_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            print("[USLawClient] WARNING: COURTLISTENER_API_KEY not set — US search disabled.")

    def _headers(self):
        return {"Authorization": f"Token {self.api_key}"}

    @staticmethod
    def _strip_html(text):
        cleaned = re.sub("<[^<]+?>", " ", text or "")
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _truncate(text, limit=200):
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    def _extract_opinion_text(self, payload):
        """Pull readable text from a CourtListener opinion or cluster payload."""
        if not payload:
            return ""
        for field in (
            "plain_text",
            "html_with_citations",
            "html",
            "xml_harvard",
            "html_lawbox",
            "html_columbia",
        ):
            raw = payload.get(field)
            if not raw:
                continue
            text = self._strip_html(raw)
            if len(text) >= 80:
                return text[:MAX_EXCERPT_CHARS]
        return ""

    def _fetch_opinion_excerpt(self, case):
        """
        Fetch actual opinion text from CourtListener so summaries stay grounded
        in source material instead of model memory.
        """
        snippet = self._strip_html(case.get("snippet") or case.get("headline") or "")
        if not self.api_key:
            return snippet

        headers = self._headers()
        cluster_id = case.get("cluster_id")
        opinion_id = case.get("opinion_id")

        fetch_urls = []
        if opinion_id:
            fetch_urls.append(f"{API_ROOT}/opinions/{opinion_id}/")
        if cluster_id:
            fetch_urls.append(f"{API_ROOT}/clusters/{cluster_id}/")

        for url in fetch_urls:
            try:
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                text = self._extract_opinion_text(data)
                if text:
                    return text

                sub_opinions = data.get("sub_opinions") or []
                for sub_url in sub_opinions[:2]:
                    if not sub_url:
                        continue
                    sub_resp = requests.get(sub_url, headers=headers, timeout=12)
                    if sub_resp.status_code != 200:
                        continue
                    text = self._extract_opinion_text(sub_resp.json())
                    if text:
                        return text
            except Exception as e:
                print(f"[USLawClient] Opinion fetch failed for {url}: {e}")

        if cluster_id:
            try:
                resp = requests.get(
                    f"{API_ROOT}/opinions/",
                    headers=headers,
                    params={"cluster": cluster_id, "page_size": 1},
                    timeout=12,
                )
                if resp.status_code == 200:
                    results = resp.json().get("results") or []
                    if results:
                        text = self._extract_opinion_text(results[0])
                        if text:
                            return text
            except Exception as e:
                print(f"[USLawClient] Cluster opinion lookup failed: {e}")

        return snippet

    @staticmethod
    def _dehedge(text):
        if not text:
            return text
        cleaned = HEDGING_WORDS.sub("", text)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([,.])", r"\1", cleaned)
        return cleaned.strip()

    @staticmethod
    def _extractive_summary(excerpt, max_sentences=3):
        """Quote-first summary when LLM would hedge on thin snippets."""
        excerpt = re.sub(r"\s+", " ", (excerpt or "").strip())
        if not excerpt:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", excerpt)
        picked = [s.strip() for s in sentences if len(s.strip()) > 40][:max_sentences]
        return " ".join(picked)

    def _build_relevance_note(self, case, incident_type, matched_query):
        title = case.get("title") or "This case"
        query = matched_query or incident_type or "insurance claim"
        snippet = self._strip_html(case.get("snippet") or case.get("headline") or "")
        topic = snippet[:120] + "..." if len(snippet) > 120 else snippet
        if topic:
            return (
                f"Retrieved for this claim via search \"{query}\" because the opinion text "
                f"references: {topic}"
            )
        return (
            f"Retrieved for this claim via search \"{query}\" as a US opinion on "
            f"insurance coverage or claims handling related to {incident_type or 'the incident'}."
        )

    def explain_claim_relevance(self, case, incident_type, matched_query=None):
        """How this US case connects to the open claim (for UI + Q&A)."""
        if not case:
            return None
        note = self._build_relevance_note(case, incident_type, matched_query)
        excerpt = self._fetch_opinion_excerpt(case)
        if not self.groq_key or len(excerpt) < 120:
            return note

        try:
            from groq import Groq
            client = Groq(api_key=self.groq_key)
            prompt = (
                f"An insurance adjuster is handling a {incident_type or 'insurance'} claim.\n"
                f"Retrieved US case: {case.get('title')}\n"
                f"Search context: {matched_query or incident_type}\n\n"
                f"Source excerpt:\n\"\"\"\n{excerpt[:1200]}\n\"\"\"\n\n"
                f"Write exactly 2 short sentences:\n"
                f"1. Why this opinion was retrieved for THIS claim type (factual, no hedging).\n"
                f"2. What specific principle from the excerpt affects claim handling here.\n"
                f"Do NOT use: likely, probably, may, might. Output only the 2 sentences."
            )
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0,
            )
            text = self._dehedge((resp.choices[0].message.content or "").strip())
            if text and not HEDGING_WORDS.search(text):
                return text
        except Exception as e:
            print(f"[USLawClient] Relevance explanation failed: {e}")
        return note

    @staticmethod
    def _excerpt_fallback_summary(case, excerpt):
        """Non-LLM summary when Groq is unavailable or returns unusable text."""
        title = case.get("title") or "This case"
        court = case.get("court") or ""
        date_filed = case.get("date_filed") or ""
        meta = ", ".join(p for p in (court, date_filed) if p)

        core = USLawClient._extractive_summary(excerpt, max_sentences=3)
        if core:
            if meta:
                return f"{title} ({meta}). {core}"
            return f"{title}. {core}"

        if meta:
            return (
                f"{title} ({meta}) is indexed on CourtListener as a US opinion relevant "
                f"to insurance coverage and claims disputes."
            )
        return (
            f"{title} is indexed on CourtListener as a US opinion relevant to "
            f"insurance coverage and claims disputes."
        )

    def _format_results(self, results, query, incident_type=None):
        """Format raw CourtListener results into our schema. Reusable across search methods."""
        formatted = []
        seen_titles = set()
        for r in results:
            title = self._strip_html(r.get("caseName") or "US Insurance Precedent")
            key = title.lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)

            snippet = self._strip_html(r.get("snippet", ""))
            abs_url = r.get("absolute_url") or ""
            cluster_id = r.get("cluster_id")
            opinion_id = r.get("id")
            case = {
                "docid": str(opinion_id or cluster_id or ""),
                "opinion_id": str(opinion_id or ""),
                "cluster_id": str(cluster_id or ""),
                "title": title,
                "headline": self._truncate(snippet, 200),
                "snippet": snippet,
                "court": r.get("court") or "",
                "date_filed": r.get("dateFiled") or r.get("date_filed") or "",
                "jurisdiction": "US",
                "url": f"https://www.courtlistener.com{abs_url}" if abs_url else "",
                "match_query": query,
            }
            case["relevance_note"] = self._build_relevance_note(
                case, incident_type or "", query
            )
            formatted.append(case)
            if len(formatted) >= 3:
                break
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

                formatted = self._format_results(results, query, incident_type)
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

        query = query or "insurance liability"
        # Bias CourtListener toward civil insurance disputes (not criminal fraud-only hits)
        if "insurance" not in query.lower():
            query = f"insurance {query}"
        return query

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
                    formatted = self._format_results(
                        results, matched_query, incident_type
                    )
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
        """Generate a grounded 2-3 sentence summary from CourtListener source text."""
        if not case:
            return None

        excerpt = self._fetch_opinion_excerpt(case)
        if not excerpt:
            return self._excerpt_fallback_summary(case, case.get("headline", ""))

        if not self.groq_key:
            return self._excerpt_fallback_summary(case, excerpt)

        try:
            from groq import Groq
            client = Groq(api_key=self.groq_key)
            court = case.get("court") or "Unknown court"
            date_filed = case.get("date_filed") or "Unknown date"
            prompt = (
                f"You are summarizing a US court opinion for an insurance claims adjuster.\n\n"
                f"Case name: {case.get('title')}\n"
                f"Court: {court}\n"
                f"Date filed: {date_filed}\n\n"
                f"Source text from CourtListener (ONLY use facts supported here):\n"
                f"\"\"\"\n{excerpt}\n\"\"\"\n\n"
                f"Write exactly 2-3 sentences that:\n"
                f"1. Identify the insurance or coverage issue discussed in the source text\n"
                f"2. Summarize the court's reasoning or outcome ONLY as stated in the source\n"
                f"3. Note practical relevance to claim handling if clearly supported\n\n"
                f"Rules:\n"
                f"- Do NOT rely on outside knowledge of the case\n"
                f"- Do NOT invent parties, holdings, damages, or procedural history\n"
                f"- If the source is only a search snippet without a clear holding, describe "
                f"the legal question or dispute topic it raises without guessing the outcome\n"
                f"- Do NOT use: likely, probably, may have, might, possibly, appears to\n"
                f"- If the excerpt is thin, state only the legal issue visible in the text\n"
                f"- Output ONLY the 2-3 sentence summary"
            )
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=220,
                temperature=0,
            )
            text = self._dehedge((resp.choices[0].message.content or "").strip())

            refusal_signals = [
                "couldn't find", "could not find", "don't have information",
                "do not have information", "unable to find", "not familiar",
                "i don't know", "no information available", "cannot determine",
                "outside knowledge", "based on the excerpt",
            ]
            if not text or HEDGING_WORDS.search(text) or any(
                sig in text.lower() for sig in refusal_signals
            ):
                fallback = self._excerpt_fallback_summary(case, excerpt)
                return fallback if fallback else text
            return text
        except Exception as e:
            print(f"[USLawClient] Brief generation failed: {e}")
            return self._excerpt_fallback_summary(case, excerpt)