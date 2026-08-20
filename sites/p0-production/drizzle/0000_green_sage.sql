CREATE TABLE `p0_state` (
	`user_key` text PRIMARY KEY NOT NULL,
	`revision` integer DEFAULT 0 NOT NULL,
	`updated_at` text NOT NULL,
	`value_json` text NOT NULL
);
