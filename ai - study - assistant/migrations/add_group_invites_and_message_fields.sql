-- Add sender_type, message_status, group_file_id to group_messages; create group_invites.
-- Run once if your DB was created before the collaborative group AI update.
-- MySQL: run each ALTER one by one; ignore errors if column already exists.

-- group_messages: new columns
-- ALTER TABLE group_messages ADD COLUMN sender_type VARCHAR(20) NOT NULL DEFAULT 'user';
-- ALTER TABLE group_messages ADD COLUMN message_status VARCHAR(20) NOT NULL DEFAULT 'sent';
-- ALTER TABLE group_messages ADD COLUMN group_file_id INT NULL;
-- ALTER TABLE group_messages ADD CONSTRAINT fk_group_message_file FOREIGN KEY (group_file_id) REFERENCES group_documents(id) ON DELETE SET NULL;
-- UPDATE group_messages SET sender_type = 'ai' WHERE message_type = 'ai' OR user_id IS NULL;

-- group_invites table
CREATE TABLE IF NOT EXISTS group_invites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    group_id INT NOT NULL,
    token VARCHAR(64) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    usage_limit INT NULL,
    used_count INT NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_group_invites_token (token),
    INDEX ix_group_invites_group_id (group_id),
    CONSTRAINT fk_group_invites_group FOREIGN KEY (group_id) REFERENCES study_groups(id) ON DELETE CASCADE
);
