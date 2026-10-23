# Mshauri | Clinic Booking System

**FastAPI + OpenStack | Python | Keycloak | Scalable & Production-Ready**

## Overview
- Display available 30-minute appointment slots by doctor and date.
- Book, cancel, and reschedule appointments.
- Prevent double-booking, including concurrent booking attempts.
- Enforce doctor working hours and appointment scheduling rules.
- Authenticate users through Keycloak.
- Authorize access according to patient, doctor, and clinic-admin roles.
- Support automated testing, repeatable deployment, and operational handover.

## Technology

- Python and FastAPI
- PostgreSQL and SQLAlchemy
- Alembic database migrations
- Keycloak with OpenID Connect
- Pytest and Postman
- Docker
- GitHub Actions
- OpenStack infrastructure

## Architecture

The application will use a modular monolith. API routes will handle HTTP
requests, services will enforce booking rules, repositories will manage
database access, and PostgreSQL will enforce data integrity.

Keycloak will provide identity and authentication. The API will enforce
authorization and validate access tokens.

Docker will package the application for deployment to an OpenStack environment.