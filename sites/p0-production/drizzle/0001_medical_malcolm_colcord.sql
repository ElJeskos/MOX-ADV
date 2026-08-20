CREATE TABLE `p0_account_locks` (
	`account_key` text PRIMARY KEY NOT NULL,
	`execution_id` text NOT NULL,
	`owner_key` text NOT NULL,
	`expires_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `p0_executions` (
	`execution_id` text PRIMARY KEY NOT NULL,
	`user_key` text NOT NULL,
	`account_key` text NOT NULL,
	`status` text NOT NULL,
	`campaign_id` text,
	`projection_json` text NOT NULL,
	`result_json` text NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
