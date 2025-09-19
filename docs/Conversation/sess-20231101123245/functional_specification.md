# Functional Specification Document

## Title Page
**Project Name:** Online Ecommerce Website for Apparel  
**Version:** 1.0  
**Date:** October 31, 2023  

---

## 1. Introduction
The purpose of this document is to outline the functional specifications for the development of an online ecommerce platform for apparel. The platform will consist of a frontend website for buyers and a web-based admin panel for business owners to manage operations. The objectives include transforming the offline apparel business into an online business, enabling buyers to search and purchase apparel online, and allowing admins to manage inventory, orders, and analytics.

---

## 2. Scope
### **In-Scope Functionality:**
#### For Buyers:
- Login/Registration.
- Search products by keyword, categories, and subcategories.
- Product listing, filtering, and sorting options.
- Product details with variations (size/color).
- Add products to wishlist and share on social media.
- Add products to cart and checkout via online payment.
- Ratings and reviews.
- Address book management.
- My account settings, order history, and order tracking.
- Contact support.

#### For Admins:
- Create/edit/delete products, categories, and subcategories.
- Manage product catalog.
- Manage orders and customers.
- Manage shipping, payments, and CMS pages.
- Review and moderate ratings and reviews.
- Access and generate statistics/reports.
- Manage user roles and permissions.

### **Out of Scope Functionality:**
- Ordering customized products.
- Real-time order tracking.
- Cash-on-delivery payment options.

---

## 3. Functional Requirements
1. Users should be able to register and log in to the ecommerce platform.
2. Users should be able to search and filter products by keywords, categories, and subcategories.
3. Users should have the ability to add products to their cart and wishlist.
4. The checkout process must allow for secure online payments.
5. Admins should be able to manage product catalog, categories, orders, and customers.
6. Admins should be able to generate useful statistics and reports.
7. Ratings and reviews must be moderated by admins.
8. The website must support user-friendly navigation and provide a seamless experience.
9. Shipping logistics must be linked to each order for tracking.
10. Integrations with external systems such as CRM, ERP, billing systems, and ticketing systems must be implemented.

---

## 4. Non-Functional Requirements
- **Scalability:** Support up to 100 concurrent users.
- **Performance:** Webpages must load within 30 seconds with a good internet connection.
- **Reliability:** Avoid broken links or 404 errors; ensure consistent uptime.
- **Security:** Implement SSL encryption for secure online payments.
- **Compliance:** Ensure adherence to GDPR for user privacy and protection of Personally Identifiable Information (PII).

---

## 5. User Roles & Personas
### **Primary Roles:**
1. **Visitors**: Search and view products, ratings, reviews, and shipping details; contact support.
2. **Buyers**: Registered users with access to full features (e.g., shopping cart, profiles, orders).
3. **Admins**: Manage products, orders, shipping, payments, and access advanced reporting tools.

**Additional roles in the future:** None anticipated.

---

## 6. Assumptions & Constraints
### **Constraints:**
1. Trainings may be required for employees to use the system effectively.
2. Changes in features or functionalities may significantly impact project timelines and costs.
3. Delivery timeline is set for October 31, 2023.
4. The budget is restricted to current resources.

### **Assumptions:**
1. Inventory is already established in physical warehouses.
2. Admin will manage the product catalog using SKU codes.
3. Pricing will be in USD, and the service will be available only in the US region.
4. No custom-size or color options for products.

---

## 7. Use Cases
### **Use Case 5: Search for Products**
- **Description**: Allow users to search for specific products using keywords and filters.
- **Actors Involved**: End User, System.
- **Preconditions**: The product catalog is populated with items.
- **Postconditions**: User sees search results and selected filters.

### Additional Cases:
- Applying Product Filters

---

## 8. Glossary
- Acronym **CRM.