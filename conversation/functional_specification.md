# Functional Specification Document

## Title Page

**Project Name:** Ecommerce Apparel Platform  
**Version:** 1.0  
**Date:** [Today’s Date]  

---

## 1. Introduction

### Overview
The project aims to develop an ecommerce platform to enable a physical apparel business to transition online, offering functionalities such as product browsing, secure transaction management, order tracking, and administrative control for catalog and inventory management.

### Objectives
- **Business Expansion:** Enhance the client’s offline business by establishing a digital presence.
- **Simple Buyer Experience:** Provide a user-friendly ecommerce experience for buyers.
- **Efficient Administration:** Enable management of products, categories, pricing, and customer orders online.

---

## 2. Scope

### Included
- **Buyers:**
  - User registration and login.
  - Product search and sort by filters.
  - Wishlist and shopping cart functionality.
  - Secure checkout and online payment.
  - Ratings, reviews, and order tracking.
- **Admin:**
  - CRUD operations on products and categories.
  - Order and customer management.
  - Shipping and payment configurations.
  - Reporting and CMS features.

### Excluded
- Ordering customized products.
- Real-time order tracking.
- Cash-on-delivery payment options.
- Shipping international orders or supporting multi-currency models.

---

## 3. Functional Requirements

### Frontend for Buyers
- **Registration/Login:** Buyers can register, authenticate, and reset passwords.
- **Browse Products:** Search products by keyword, category, or filters.
- **Cart and Wishlist:** Add items with options to edit quantities prior to checkout.
- **Checkout:** Make payments securely via integrated gateways.
- **Ratings & Reviews:** Provide feedback on products.
- **Order Tracking:** Check shipping status post-purchase.

### Backend for Admins
- **Product Management:** Add/edit/delete product listings, stock information.
- **Order Management:** Track and manage customer purchases.
- **Customer Management:** Handle buyer accounts and queries.
- **CMS:** Modify static content such as FAQs and policies.
- **Reporting:** Generate statistical insights via dashboards.

---

## 4. Non-Functional Requirements

- **Scalability:** Handle up to 100 concurrent users.
- **Speed:** Ensure all pages load within 30 seconds in ideal conditions.
- **Reliability:** Guarantee no broken links or unresponsive pages.
- **Security:**
  - SSL encryption for secure payment processing.
  - Data protection measures in compliance with US regulations.
- **Availability:** Ensure system maintenance does not disrupt operations significantly.

---

## 5. User Roles & Personas

### Roles
#### Visitors
- Product browsing functionality without registration.

#### Registered Buyers
- Advanced account-specific options for purchasing, tracking, and reviewing.

#### Admin (Business Owner)
- Operational control over inventory, order management, users, and financial reporting.

---

## 6. Assumptions & Constraints

### Assumptions
- Physical inventory and warehouse setup exist.
- Admin will manage the product catalog, assigning SKUs as appropriate.
- Platform will only support USD pricing for US-based customers.

### Constraints
- **Budget:** Project spending is limited to the outlined scope.
- **Timeline:** Delivery deadline is set to October 31.
- **Training:** Admin users will require orientation and system support post-deployment.

---

## 7. Use Cases

### Use Cases Provided

1. **User Registration**: Users create accounts, verify emails, and gain access.
2. **Browse Products by Category**: Users navigate products within predefined classifications.
3. **Add Items to Shopping Cart**: Users select products for purchase and validation.
4. **Checkout Process**: Completed cart submissions, payment, and email confirmations.
5. **Track Delivery Status**: Real-time shipment updates integrated via APIs.

### User Stories

1. **Registration Story**: Track account verification.
2. **Categories Story**: Navigate top-level product organization.
3. **Adding Cart Products**: Manage product quantity and optional wishlists.
4. **Checkout & Secure**: Handle transactions fast enough for B2B.

---

## 8. Glossary of Terms

### Terms Added

Authentication, Auth Tags,wider actions for consistently checking anytime...,