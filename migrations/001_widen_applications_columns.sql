-- Run this once against your EXISTING pursuit database.
-- It widens applications columns to match the Pydantic max_length validators
-- in main.py's ApplicationInput — right now several columns (e.g. `company`
-- varchar(30) vs. the API's 200-char limit) are narrower than what the API
-- will accept, so a long-but-valid submission passes validation and then
-- fails with a raw MySQL "Data too long" error instead of a clean 422.
--
-- Safe to run any time; only widens columns, doesn't touch data.
-- mysql -u root pursuit < migrations/001_widen_applications_columns.sql

ALTER TABLE `applications`
  MODIFY `company` varchar(200) NOT NULL,
  MODIFY `role` varchar(200) NOT NULL,
  MODIFY `location` varchar(200) NOT NULL,
  MODIFY `source` varchar(50) NOT NULL,
  MODIFY `status` varchar(50) NOT NULL,
  MODIFY `salary` varchar(100) NOT NULL,
  MODIFY `jobType` varchar(50) NOT NULL,
  MODIFY `contact` varchar(200) DEFAULT NULL,
  MODIFY `contactEmail` varchar(254) DEFAULT NULL,
  MODIFY `tags` varchar(500) DEFAULT NULL,
  MODIFY `resumeFileName` varchar(255) DEFAULT NULL,
  MODIFY `rejectionReason` varchar(500) DEFAULT NULL;
