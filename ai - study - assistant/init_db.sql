-- AI Study Assistant - MySQL Database Setup
-- Run this script to create the database

CREATE DATABASE IF NOT EXISTS ai_study_assistant 
    CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

USE ai_study_assistant;

-- Tables are created automatically by SQLAlchemy on first run
-- This file is for reference. The application creates tables from models.

-- Expected tables (created by backend):
-- users: id, email, hashed_password, created_at
-- documents: id, user_id, filename, extracted_text, created_at
-- summaries: id, document_id, content, created_at
-- questions: id, document_id, content_json, created_at
