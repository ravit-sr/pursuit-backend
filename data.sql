-- Pursuit database schema
-- Regenerated from the live DB on 2026-07-28 — structure only, no user data.
-- Import with: mysql -u root pursuit < data.sql  (or via phpMyAdmin > Import)

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";

CREATE DATABASE IF NOT EXISTS `pursuit` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE `pursuit`;

-- --------------------------------------------------------

--
-- Table structure for table `users`
--

CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `firstName` varchar(20) NOT NULL,
  `lastName` varchar(20) NOT NULL,
  `email` varchar(50) NOT NULL,
  `password` varchar(100) DEFAULT NULL,
  `location` varchar(100) DEFAULT NULL,
  `experienceLevel` varchar(30) DEFAULT NULL,
  `bio` varchar(100) DEFAULT NULL,
  `linkedinUrl` varchar(100) DEFAULT NULL,
  `githubUrl` varchar(100) DEFAULT NULL,
  `website` varchar(100) DEFAULT NULL,
  `authProvider` varchar(20) DEFAULT 'local',
  `avatarFileName` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --------------------------------------------------------

--
-- Table structure for table `applications`
--

CREATE TABLE `applications` (
  `id` int NOT NULL AUTO_INCREMENT,
  `userId` int NOT NULL,
  `company` varchar(200) NOT NULL,
  `role` varchar(200) NOT NULL,
  `location` varchar(200) NOT NULL,
  `source` varchar(50) NOT NULL,
  `status` varchar(50) NOT NULL,
  `salary` varchar(100) NOT NULL,
  `jobType` varchar(50) NOT NULL,
  `contact` varchar(200) DEFAULT NULL,
  `contactEmail` varchar(254) DEFAULT NULL,
  `dateApplied` date NOT NULL,
  `interviewDate` date DEFAULT NULL,
  `followUpDate` date DEFAULT NULL,
  `notes` text,
  `coverLetter` text,
  `tags` varchar(500) DEFAULT NULL,
  `resumeFileName` varchar(255) DEFAULT NULL,
  `rejectionReason` varchar(500) DEFAULT NULL,
  `calendarEventId` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `userId` (`userId`),
  CONSTRAINT `applications_ibfk_1` FOREIGN KEY (`userId`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --------------------------------------------------------

--
-- Table structure for table `resumes`
--

CREATE TABLE `resumes` (
  `id` int NOT NULL AUTO_INCREMENT,
  `userId` int NOT NULL,
  `fileName` varchar(255) NOT NULL,
  `storedFileName` varchar(255) NOT NULL,
  `fileSize` int NOT NULL,
  `uploadedAt` datetime DEFAULT CURRENT_TIMESTAMP,
  `active` tinyint(1) DEFAULT '0',
  `analysisJson` text,
  `analyzedAt` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `userId` (`userId`),
  CONSTRAINT `resumes_ibfk_1` FOREIGN KEY (`userId`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --------------------------------------------------------

--
-- Table structure for table `resume_chats`
--

CREATE TABLE `resume_chats` (
  `id` int NOT NULL AUTO_INCREMENT,
  `userId` int NOT NULL,
  `resumeId` int NOT NULL,
  `title` varchar(100) NOT NULL DEFAULT 'New Chat',
  `createdAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `userId` (`userId`),
  KEY `resumeId` (`resumeId`),
  CONSTRAINT `resume_chats_ibfk_1` FOREIGN KEY (`userId`) REFERENCES `users` (`id`),
  CONSTRAINT `resume_chats_ibfk_2` FOREIGN KEY (`resumeId`) REFERENCES `resumes` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --------------------------------------------------------

--
-- Table structure for table `resume_chat_messages`
--

CREATE TABLE `resume_chat_messages` (
  `id` int NOT NULL AUTO_INCREMENT,
  `chatId` int NOT NULL,
  `role` varchar(10) NOT NULL,
  `message` text NOT NULL,
  `createdAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `chatId` (`chatId`),
  CONSTRAINT `resume_chat_messages_ibfk_1` FOREIGN KEY (`chatId`) REFERENCES `resume_chats` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --------------------------------------------------------

--
-- Table structure for table `user_ai_insights`
--

CREATE TABLE `user_ai_insights` (
  `id` int NOT NULL AUTO_INCREMENT,
  `userId` int NOT NULL,
  `insightsJson` text,
  `generatedAt` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `userId` (`userId`),
  CONSTRAINT `user_ai_insights_ibfk_1` FOREIGN KEY (`userId`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --------------------------------------------------------

--
-- Table structure for table `user_integrations`
--

CREATE TABLE `user_integrations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `userId` int NOT NULL,
  `serviceName` varchar(30) NOT NULL,
  `connected` tinyint(1) DEFAULT '0',
  `accountLabel` varchar(255) DEFAULT NULL,
  `accessToken` text,
  `refreshToken` text,
  `tokenExpiry` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `userId` (`userId`),
  CONSTRAINT `user_integrations_ibfk_1` FOREIGN KEY (`userId`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --------------------------------------------------------

--
-- Table structure for table `user_settings`
--

CREATE TABLE `user_settings` (
  `id` int NOT NULL AUTO_INCREMENT,
  `userId` int NOT NULL,
  `theme` varchar(10) DEFAULT 'system',
  `accentColor` varchar(10) DEFAULT '#4f8ef7',
  `fontSize` varchar(10) DEFAULT '14px',
  `compactTable` tinyint(1) DEFAULT '0',
  `statusEmojis` tinyint(1) DEFAULT '1',
  `notifWeekly` tinyint(1) DEFAULT '1',
  `notifInterview` tinyint(1) DEFAULT '1',
  `notifFollowup` tinyint(1) DEFAULT '1',
  `notifTips` tinyint(1) DEFAULT '0',
  `notifUpdates` tinyint(1) DEFAULT '0',
  `notifFrequency` varchar(20) DEFAULT 'Weekly',
  `goalRole` varchar(50) DEFAULT NULL,
  `goalIndustry` varchar(50) DEFAULT NULL,
  `goalSalary` varchar(20) DEFAULT NULL,
  `goalLocations` varchar(200) DEFAULT NULL,
  `goalWeeklyTarget` int DEFAULT '0',
  `goalDeadline` date DEFAULT NULL,
  `goalFulltime` tinyint(1) DEFAULT '1',
  `goalRemote` tinyint(1) DEFAULT '1',
  `goalContract` tinyint(1) DEFAULT '0',
  `goalPartTime` tinyint(1) DEFAULT '0',
  `privacyProfileVisibility` tinyint(1) DEFAULT '1',
  `privacyAnonymousAnalytics` tinyint(1) DEFAULT '1',
  `privacyAiTrainingOptIn` tinyint(1) DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_user` (`userId`),
  CONSTRAINT `user_settings_ibfk_1` FOREIGN KEY (`userId`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

COMMIT;
