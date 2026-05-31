/**
 * Sends Case + emails + call logs to RiskRadar webhook.
 *
 * Setup:
 *   1. Remote Site: https://YOUR-APP.onrender.com
 *   2. Set WEBHOOK_URL and WEBHOOK_SECRET below (or use Custom Labels)
 *   3. Flow on Case (create/update) + optional Flow on Task after Log a Call
 *   4. Link Contact on Case for claimant name / age / state
 *
 * Emails appear as EmailMessage rows — use "Email" action on Case or Email-to-Case.
 * Calls appear as Task rows with Call Type set — use "Log a Call" on Case.
 */
public with sharing class RiskRadarCaseSync {

    // --- CONFIG: edit for your org ---
    private static final String WEBHOOK_URL = 'https://YOUR-APP.onrender.com/integrations/salesforce/webhook';
    private static final String WEBHOOK_SECRET = 'RrSf_2026_xK9mP2vL7nQ4';

    public class Request {
        @InvocableVariable(required=true label='Case Id')
        public Id caseId;
    }

    @InvocableMethod(label='Send Case to RiskRadar')
    public static void sendToRiskRadar(List<Request> requests) {
        for (Request req : requests) {
            syncCase(req.caseId);
        }
    }

    @future(callout=true)
    public static void syncCase(Id caseId) {
        Case c = [
            SELECT Id, CaseNumber, Subject, Description, Type, Reason, ContactId,
                   Contact.Name, Contact.MailingState, Contact.Birthdate,
                   Policy_Type__c, Total_Claimed__c, Insurer_Offer__c,
                   Injury_Severity__c, Followup_Contacts__c, Doc_Requests__c,
                   Disputed_Items__c, Inspections__c, Legal_Rep__c,
                   Adjuster_Level__c, Payment_Status__c, DOI_Complaint__c,
                   Policy_Tenure_Yrs__c, CreatedDate
            FROM Case
            WHERE Id = :caseId
            LIMIT 1
        ];

        List<Object> activities = new List<Object>();
        activities.addAll(getEmailActivities(caseId));
        activities.addAll(getCallAndTaskActivities(caseId));
        activities.addAll(getCaseComments(caseId));

        Integer claimantAge = null;
        if (c.Contact != null && c.Contact.Birthdate != null) {
            claimantAge = c.Contact.Birthdate.daysBetween(Date.today()) / 365;
        }

        Integer daysOpen = c.CreatedDate != null
            ? c.CreatedDate.date().daysBetween(Date.today())
            : 0;

        Map<String, Object> payload = new Map<String, Object>{
            'claim_id' => 'SF-' + c.CaseNumber,
            'salesforce_case_id' => c.Id,
            'salesforce_case_number' => c.CaseNumber,
            'claimant_name' => c.Contact != null ? c.Contact.Name : c.Subject,
            'age' => claimantAge,
            'incident_description' => c.Description,
            'policy_type' => c.Policy_Type__c,
            'incident_type' => c.Type != null ? c.Type : c.Reason,
            'injury_severity' => c.Injury_Severity__c,
            'state' => c.Contact != null ? c.Contact.MailingState : null,
            'days_open' => daysOpen,
            'total_claimed' => c.Total_Claimed__c,
            'insurer_offer' => c.Insurer_Offer__c,
            'policy_tenure_yrs' => c.Policy_Tenure_Yrs__c,
            'followup_contacts' => c.Followup_Contacts__c,
            'doc_requests' => c.Doc_Requests__c,
            'disputed_items' => c.Disputed_Items__c,
            'inspections' => c.Inspections__c,
            'legal_rep' => c.Legal_Rep__c,
            'adjuster_level' => c.Adjuster_Level__c,
            'payment_status' => c.Payment_Status__c,
            'doi_complaint' => (c.DOI_Complaint__c == true) ? 1 : 0,
            'activities' => activities
        };

        HttpRequest httpReq = new HttpRequest();
        httpReq.setEndpoint(WEBHOOK_URL);
        httpReq.setMethod('POST');
        httpReq.setHeader('Content-Type', 'application/json');
        httpReq.setHeader('X-RiskRadar-Secret', WEBHOOK_SECRET);
        httpReq.setBody(JSON.serialize(payload));
        httpReq.setTimeout(120000);

        HttpResponse res = new Http().send(httpReq);
        System.debug('RiskRadar HTTP ' + res.getStatusCode() + ': ' + res.getBody());
    }

    /** Emails on Case — ParentId OR RelatedToId depending on org */
    private static List<Object> getEmailActivities(Id caseId) {
        List<Object> out = new List<Object>();
        for (EmailMessage em : [
            SELECT Subject, TextBody, HtmlBody, FromAddress, ToAddress, MessageDate, Incoming
            FROM EmailMessage
            WHERE ParentId = :caseId OR RelatedToId = :caseId
            ORDER BY MessageDate DESC NULLS LAST
            LIMIT 15
        ]) {
            String body = String.isNotBlank(em.TextBody) ? em.TextBody : stripHtml(em.HtmlBody);
            if (String.isBlank(body) && String.isBlank(em.Subject)) continue;
            out.add(new Map<String, Object>{
                'type' => 'email',
                'subject' => em.Subject,
                'body' => body,
                'from' => em.FromAddress,
                'incoming' => em.Incoming
            });
        }
        return out;
    }

    /** Log a Call + Tasks on Case */
    private static List<Object> getCallAndTaskActivities(Id caseId) {
        List<Object> out = new List<Object>();
        for (Task t : [
            SELECT Subject, Description, Type, TaskSubtype, CallType, CallDurationInSeconds, Status
            FROM Task
            WHERE WhatId = :caseId
            ORDER BY CreatedDate DESC
            LIMIT 15
        ]) {
            Boolean isCall = (t.CallType != null) || (t.TaskSubtype == 'Call');
            String kind = isCall ? 'call' : 'task';
            String body = t.Description;
            if (isCall && t.CallDurationInSeconds != null) {
                body = (body != null ? body + '\n' : '') + 'Duration (sec): ' + t.CallDurationInSeconds;
            }
            out.add(new Map<String, Object>{
                'type' => kind,
                'subject' => t.Subject,
                'body' => body,
                'status' => t.Status
            });
        }
        return out;
    }

    /** Chatter / case comments (internal notes) */
    private static List<Object> getCaseComments(Id caseId) {
        List<Object> out = new List<Object>();
        for (CaseComment cc : [
            SELECT CommentBody, CreatedDate, IsPublished
            FROM CaseComment
            WHERE ParentId = :caseId
            ORDER BY CreatedDate DESC
            LIMIT 10
        ]) {
            if (String.isBlank(cc.CommentBody)) continue;
            out.add(new Map<String, Object>{
                'type' => 'note',
                'subject' => 'Case comment',
                'body' => cc.CommentBody
            });
        }
        return out;
    }

    private static String stripHtml(String html) {
        if (String.isBlank(html)) return '';
        return html.replaceAll('<[^>]+>', ' ').replaceAll('\\s+', ' ').trim();
    }
}
