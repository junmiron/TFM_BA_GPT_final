# Functional Specification Document

---

## **Title Page**
**Project Name:** Ecommerce Website for Apparel Business  
**Version:** 1.0  
**Date:** October 2023  

---

## **1. Introduction**
### **Overview and Objectives**
The purpose of this project is to transform the client's offline apparel business into an online ecommerce platform. This platform will enable customers to browse and purchase apparel online, while providing the business owner with a backend system to manage products, categories, pricing, and customer orders efficiently.

---

## **2. Scope**
### **In Scope**
- Buyer functionalities: 
  - Login, Registration, Product search, Wishlist, Shopping Cart, Order placement, Ratings/Reviews, Order tracking, and Notifications.
- Admin functionalities: 
  - Product, order, customer, shipping and payment management, Content Management System (CMS), and Analytics/Reporting tools.
- Integration with external systems like CRM, ERP, and payment gateways.

### **Out of Scope**
- Custom product ordering.
- Real-time order tracking.
- Cash-on-delivery payment option.

---

## **3. Functional Requirements**
1. Users (both buyers and visitors) must be able to search for products using filters and categories.
2. Buyers must be able to add items to their cart and complete the checkout process with secure online payments.
3. Registered buyers must have access to order history and tracking features.
4. Admin users must be able to manage the product catalog, including categories, descriptions, and inventory levels.
5. The platform must send automated email notifications for successful registrations, order placements, and shipping updates.
6. Integration with external systems for payment, order processing, and customer support must be seamless.

---

## **4. Non-Functional Requirements**
1. The platform must be scalable to accommodate up to 100 concurrent users.
2. Pages must load within 30 seconds on a good internet connection.
3. The platform must support SSL security for secure online payments.
4. The platform must comply with GDPR for handling PII.
5. Ensure high availability and reliability, with minimal downtime.

---

## **5. User Roles & Personas**
### **Visitors**
- Search products, view details, and share items on social media.

### **Buyers**
- Register/Login, purchase products, track orders, and post ratings/reviews.

### **Admin (Business Owner)**
- Manage product catalog, orders, customers, shipping, payments, roles/permissions, CMS pages, and reporting tools.

---

## **6. Assumptions & Constraints**
### **Assumptions:**
- An existing physical inventory and warehouse are in place.
- All products have an associated SKU for tracking.
- The platform will accept payments exclusively in USD and serve US-based customers.

### **Constraints:**
- Budget and timeline are fixed, with a delivery date set for October 31st.
- Additional feature requests may impact cost and project timelines.

---

## **7. Use Cases**
### **Use Case 1: Browse and Search Products**
**Description:** Enable visitors and buyers to search and browse products using categories and filters.

**Actors:** Visitor, Buyer

**Preconditions:** Website is accessible; product catalog is populated.

**Postconditions:** Products displayed based on search criteria.

**Flow:**
1. User accesses homepage, enters search terms, or selects categories.
2. Platform retrieves relevant products and displays results.
3. User accesses product details for specific selections.

### **Use Case 2: User Registration**
**Description:** Allow new visitors to register accounts.

**Actors:** Visitor

**Preconditions:** User is on registration page.

**Postconditions:** Registration confirmation sent.

**Flow:**
1. User submits information; system validates.
2. Sends verification email.
3. User completes registration via email link.

...
(Refer to generated detailed use cases for more scenarios.)

---

## **8. Glossary**
Below are terms related to ecommerce:

- **SKU:** Unique identifier for product tracking.
- **SSL:** Encryption protocol for secure online transactions.
- **GDPR:** EU regulation for data privacy compliance.
- **PII:** Data that identifies an individual, like email, phone, etc.
- **CMS:** Content Management System to manage website content.
- **Payment Gateway:** Service used for processing online payments securely.

---

---

## Process Diagram

![Process Diagram](process_diagram.png){ width=95% }

