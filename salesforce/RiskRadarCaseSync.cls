/**
 * Optional Apex invocable from Flow — posts Case + activities to RiskRadar.
 * Setup: Remote Site Settings → your Render URL
 *         Custom Setting or Named Credential for webhook URL + secret
 */
public with sharing class RiskRadarCaseSync {

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
            SELECT Id, CaseNumber, Subject, Description, Type, Reason,
                   Contact.Name, Contact.MailingState,
                   Policy_Type__c, Total_Claimed__c, Insurer_Offer__c,
                   Injury_Severity__c, Follow_up_Contacts__c, Doc_Requests__c,
                   Disputed_Items__c, Inspections__c, Legal_Rep__c,
                   Adjuster_Level__c, Payment_Status__c, DOI_Complaint__c,
                   CreatedDate
            FROM Case
            WHERE Id = :caseId
            LIMIT 1
        ];

        List<Object> activities = new List<Object>();

        for (EmailMessage em : [
            SELECT Subject, TextBody, CreatedDate
            FROM EmailMessage
            WHERE ParentId = :caseId
            ORDER BY CreatedDate DESC
            LIMIT 10
        ]) {
            activities.add(new Map<String, Object>{
                'type' => 'email',
                'subject' => em.Subject,
                'body' => em.TextBody
            });
        }

        for (Task t : [
            SELECT Subject, Description, Type, CallType
            FROM Task
            WHERE WhatId = :caseId
            ORDER BY CreatedDate DESC
            LIMIT 10
        ]) {
            String kind = (t.CallType != null) ? 'call' : 'task';
            activities.add(new Map<String, Object>{
                'type' => kind,
                'subject' => t.Subject,
                'body' => t.Description
            });
        }

        Integer daysOpen = c.CreatedDate != null
            ? c.CreatedDate.date().daysBetween(Date.today())
            : 0;

        Map<String, Object> payload = new Map<String, Object>{
            'claim_id' => 'SF-' + c.CaseNumber,
            'salesforce_case_id' => c.Id,
            'salesforce_case_number' => c.CaseNumber,
            'claimant_name' => c.Contact != null ? c.Contact.Name : c.Subject,
            'incident_description' => c.Description,
            'policy_type' => c.Policy_Type__c,
            'incident_type' => c.Type != null ? c.Type : c.Reason,
            'injury_severity' => c.Injury_Severity__c,
            'state' => c.Contact != null ? c.Contact.MailingState : null,
            'days_open' => daysOpen,
            'total_claimed' => c.Total_Claimed__c,
            'insurer_offer' => c.Insurer_Offer__c,
            'followup_contacts' => c.Follow_up_Contacts__c,
            'doc_requests' => c.Doc_Requests__c,
            'disputed_items' => c.Disputed_Items__c,
            'inspections' => c.Inspections__c,
            'legal_rep' => c.Legal_Rep__c,
            'adjuster_level' => c.Adjuster_Level__c,
            'payment_status' => c.Payment_Status__c,
            'doi_complaint' => c.DOI_Complaint__c != null && c.DOI_Complaint__c ? 1 : 0,
            'activities' => activities
        };

        HttpRequest httpReq = new HttpRequest();
        httpReq.setEndpoint('callout:RiskRadar/webhook'); // Named Credential preferred
        // Or hardcode for hackathon: https://YOUR-APP.onrender.com/integrations/salesforce/webhook
        httpReq.setMethod('POST');
        httpReq.setHeader('Content-Type', 'application/json');
        httpReq.setHeader('X-RiskRadar-Secret', '{!$Credential.Password}'); // or Custom Label
        httpReq.setBody(JSON.serialize(payload));
        httpReq.setTimeout(120000);

        Http http = new Http();
        HttpResponse res = http.send(httpReq);
        System.debug('RiskRadar status: ' + res.getStatusCode() + ' ' + res.getBody());
    }
}
