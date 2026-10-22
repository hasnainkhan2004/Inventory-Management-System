# Inventory Management System

A Django web application for managing products and monitoring inventory levels.

## Features

- Product creation, editing, deletion, and search by name or SKU
- Inventory dashboard with product count, total stock value, and low-stock alerts
- User login and Django admin access

## Setup

```bash
git clone https://github.com/hasnainkhan2004/Inventory-Management-System.git
cd Inventory-Management-System
python -m venv venv
```

Activate the virtual environment, then install Django:

```bash
pip install Django==6.0.6
```

Apply database migrations and create an admin user:

```bash
python manage.py migrate
python manage.py createsuperuser
```

Start the development server:

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000/` to use the application. Sign in with the user you created. The Django admin is available at `http://127.0.0.1:8000/admin/`.
