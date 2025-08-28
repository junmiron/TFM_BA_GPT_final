# Functional Specification Document

## Title Page
**Project Name**: AI Dialer for Travel Packages

**Version**: 1.0

**Date**: 2023-11-03

---

## Introduction
The purpose of this project is to develop an AI-powered dialer system designed to call customers and offer travel packages. The AI will handle call interactions, transfer customers to human agents for finalizing deals, and aim to improve efficiency and customer engagement. By leveraging integrations with existing systems, the AI dialer will streamline outbound campaigns and provide comprehensive reporting on KPIs.

---

## Scope
### In-Scope Features
1. Integration with the call center to:
   - Initiate and transfer calls.
   - Support up to 300 simultaneous calls.
2. Integration with CRM systems for accessing the following customer details:
   - Name, phone number, location, and salary.
3. Database usage for:
   - Predefined offers and responses.
   - Storing call results (successful, rejected, or error calls).
   - Storing additional resources for generating responses to customer questions using a Rules and Guidance System (RAG).
4. Generation of end-of-shift metrics and KPIs, which include:
   - Successful calls, errors, successful deals, and rejected deals.
   - Reports featuring charts, tables, and a dynamic dashboard.
5. Real-time decision-making based on predefined offers and call status.


### Business Requirements

| Business Requirement ID | Description |
| --- | --- |
| BR1 | Integration with the call center to: Initiate and transfer calls.; Support up to 300 simultaneous calls. |
| BR2 | Integration with CRM systems for accessing the following customer details: Name, phone number, location, and salary. |
| BR3 | Database usage for: Predefined offers and responses.; Storing call results (successful, rejected, or error calls).; Storing additional resources for generating responses to customer questions using a Rules and Guidance System (RAG). |
| BR4 | Generation of end-of-shift metrics and KPIs, which include: Successful calls, errors, successful deals, and rejected deals.; Reports featuring charts, tables, and a dynamic dashboard. |
| BR5 | Real-time decision-making based on predefined offers and call status. |

### Out-of-Scope Features
1. Integration with WhatsApp or other social networks.
2. Expansion to non-English languages.

---

## Functional Requirements
1. The AI dialer must integrate with the call center system to initiate, manage, and transfer calls in real time.
2. The AI must access relevant customer data from the CRM system during the call execution process.
3. The system must store and retrieve predefined offers and responses from a database.
4. The AI should generate reports at the end of each shift, summarizing KPIs and metrics.
5. The system should allow marketing teams to update offers and predefined responses in the database.
6. Calls should operate only within the hours of 8:00 AM to 5:00 PM.
7. All data, including call results and customer interactions, must be stored securely with encryption.

---


### Functional Requirements Mapping

| Business Requirement ID | Functional Requirement ID | Description |
| --- | --- | --- |
| BR1 | FR1 | The AI dialer must integrate with the call center system to initiate, manage, and transfer calls in real time. |
| BR2 | FR2 | The AI must access relevant customer data from the CRM system during the call execution process. |
| BR3 | FR3 | The system must store and retrieve predefined offers and responses from a database. |
| BR4 | FR4 | The AI should generate reports at the end of each shift, summarizing KPIs and metrics. |
| BR5 | FR5 | The system should allow marketing teams to update offers and predefined responses in the database. |
|  | FR6 | Calls should operate only within the hours of 8:00 AM to 5:00 PM. |
|  | FR7 | All data, including call results and customer interactions, must be stored securely with encryption. --- |
## Non-Functional Requirements
1. **Performance**:
   - Support up to 300 simultaneous calls.
2. **Availability and Reliability**:
   - Ensure a system availability of 99.96%.
3. **Language & Voice Quality**:
   - Support only the English language.
   - Use natural language processing to achieve human-like voice quality with respectful and convincing tones.
4. **Security**:
   - Comply with GDPR and PII regulations.
   - Implement access controls: developers have full access, while the marketing team has restricted access to reports.
5. **Usability**:
   - Follow best practices for UI/UX design.

---

## User Roles & Personas

### Internal Users
1. **Marketing Team**:
   - Updates predefined offers, answers, and reports.
2. **Human Agents**:
   - Handle transferred calls and close deals.
3. **IT Team**:
   - Provide technical support and ongoing system maintenance.
4. **Sponsor**:
   - Marketing VP oversees funding and priority alignment.

### External Users
1. **Travel Agencies and Airlines**:
   - Organizations using the system to connect with end customers.
2. **Final Customers**:
   - Recipients of the AI dialer calls.

---

## Assumptions & Constraints
### Assumptions
1. The marketing team will provide predefined offers and customer surveys to input in the database.
2. The IT team has suitable resources for system deployment and maintenance.

### Constraints
1. Calls will be restricted to working hours (8:00 AM–5:00 PM).
2. The system must comply with GDPR and PII regulations.
3. All offers and answers are predefined and stored in the database.

---

## Use Cases
### **Use Case 1: Make an Outbound Call**
#### Description:
The AI Dialer enables human agents to make outbound calls efficiently to customers, providing behavioral insights to tailor the call experience.

#### Actors:
- Human Agents
- Customers

#### Preconditions:
1. The agent must be logged into the AI Dialer system.
2. The customer’s contact information must exist in the database.
3. The outbound call feature must be enabled for the agent.

#### Postconditions:
1. The customer receives the call.
2. The system records call details such as duration, outcome, and notes.

#### Main Flow:
1. The agent initiates the outbound call through the AI Dialer system.
2. The AI Dialer retrieves the customer's contact information from the database.
3. The system analyzes the mood and behavior of the customer using past interactions or real-time data.
4. The dialer connects the call to the customer.
5. The agent communicates with the customer.
6. At the end of the call, the system prompts the agent to record notes and the call outcome.
7. If applicable, the system suggests follow-up actions based on the call's result.

#### Alternate Flows:
1. **Call Fails to Connect:**
   1.1 The system retries the call three times before marking it as "Failed to Connect."
   1.2 A notification is sent to the agent regarding failure.

2. **Customer Busy:**
   2.1 The system schedules a callback and notifies the agent.

---

### **Use Case 2: Generate Call Reports**
#### Description:
The AI Dialer provides detailed call reports for the marketing team and IT support to analyze performance and troubleshoot issues.

#### Actors:
- Marketing Teams
- IT Support

#### Preconditions:
1. Reports must have data from completed calls.
2. The user must have access permissions to view reports.

#### Postconditions:
1. A summarized report is generated with metrics like call duration, success rate, and agent performance.
2. Users can download or share the report for further analysis.

#### Main Flow:
1. The user logs into the AI Dialer system.
2. The user navigates to the reporting module.
3. The user requests a custom report by selecting filters such as date range, agent ID, or call outcomes.
4. The system processes and generates the report.
5. The user views the report on the screen and downloads it if necessary.

#### Alternate Flows:
1. **Missing Data:**
   1.1 The system alerts the user about incomplete or missing records relevant to the report.
   1.2 The user can adjust the filters or wait for the data to refresh.

2. **Export Error:**
   2.1 The system retries the export process automatically.
   2.2 If unsuccessful, the system prompts the user to make manual corrections.

---

## Glossary
### Business Terms
- **CRM (Customer Relationship Management):** A system or software that manages a company's interactions with current and potential customers. In the context of AI Dialer, CRM integration allows for optimized customer outreach and data handling.
- **KPI (Key Performance Indicator):** Metrics used to evaluate the success of specific activities or overall performance. In the AI Dialer system, KPIs could include call success rates, conversion rates, and average call handling time.
- **GDPR Compliance (General Data Protection Regulation Compliance):** Adherence to data protection and privacy laws established by the European Union. For AI Dialers, this means safeguarding customer information during data storage, transmission, and processing.

### Technical Terms
- **SIP (Session Initiation Protocol):** A communication protocol used for initiating, maintaining, and terminating real-time sessions, like voice and video calls. Crucial for AI Dialers in interacting with VoIP systems.
- **Natural Language Processing (NLP):** A field of artificial intelligence focused on enabling computers to understand, interpret, and respond to human language. In AI Dialers, NLP is used for interpreting customer speech and generating appropriate responses.
- **RAG (Red-Amber-Green):** A status indicator framework frequently used in project management. For AI Dialers, it could represent live monitoring of system performance or issue resolution status.

### System Features
- **Predefined Responses:** A library of canned or templated answers programmed into the AI Dialer for common queries or circumstances, ensuring quick and consistent communication.
- **Navigation:** Tools and features within the AI Dialer interface that assist users in moving through the system efficiently.

### General Terms
- **Communication Protocols:** Standards governing the exchange of information between systems and devices. In AI Dialer software, robust protocols ensure reliable and flexible communication processes.
- **Interoperability:** The capability of the AI Dialer system to integrate with other software or systems (e.g., CRM, VoIP platforms) seamlessly.

## Process Diagram

![Process Diagram](process_diagram.png){ width=95% }

