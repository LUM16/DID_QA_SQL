-- Run this while connected to the default "postgres" database in pgManage.
-- Do not store application data in the "postgres" system database.
-- After this succeeds, switch the connection / query session to did_qa.

CREATE DATABASE did_qa;
