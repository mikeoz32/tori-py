-- Demo-only local development roles. Do not reuse these passwords.
CREATE ROLE keycloak_demo LOGIN PASSWORD 'keycloak-demo-only';
CREATE ROLE spaces_demo LOGIN PASSWORD 'spaces-demo-only';
CREATE ROLE bookings_demo LOGIN PASSWORD 'bookings-demo-only';
CREATE ROLE notifications_demo LOGIN PASSWORD 'notifications-demo-only';

CREATE DATABASE keycloak OWNER keycloak_demo;
CREATE DATABASE spaces OWNER spaces_demo;
CREATE DATABASE bookings OWNER bookings_demo;
CREATE DATABASE notifications OWNER notifications_demo;
\connect bookings
CREATE EXTENSION IF NOT EXISTS btree_gist;
