CREATE TABLE IF NOT EXISTS `p0_state_revisions` (
	`user_key` text NOT NULL,
	`revision` integer NOT NULL,
	`updated_at` text NOT NULL,
	`value_json` text NOT NULL,
	PRIMARY KEY(`user_key`, `revision`)
);
