-- Migration: Add page_data_path and total_pages to documents table
-- Run this if you get "Unknown column 'documents.page_data_path'" error

USE ai_study_assistant;

ALTER TABLE documents 
ADD COLUMN page_data_path VARCHAR(500) NULL AFTER content_path,
ADD COLUMN total_pages INT NULL AFTER page_data_path;
