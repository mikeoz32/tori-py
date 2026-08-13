CREATE ROLE catalog LOGIN PASSWORD 'catalog';
CREATE ROLE orders LOGIN PASSWORD 'orders';
CREATE ROLE notifications LOGIN PASSWORD 'notifications';

CREATE DATABASE catalog OWNER catalog;
CREATE DATABASE orders OWNER orders;
CREATE DATABASE notifications OWNER notifications;
