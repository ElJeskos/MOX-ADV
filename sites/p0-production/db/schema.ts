import { integer, primaryKey, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const p0States = sqliteTable("p0_state", {
  userKey: text("user_key").primaryKey(),
  revision: integer("revision").notNull().default(0),
  updatedAt: text("updated_at").notNull(),
  valueJson: text("value_json").notNull(),
});

export const p0StateRevisions = sqliteTable("p0_state_revisions", {
  userKey: text("user_key").notNull(),
  revision: integer("revision").notNull(),
  updatedAt: text("updated_at").notNull(),
  valueJson: text("value_json").notNull(),
}, (table) => [primaryKey({ columns: [table.userKey, table.revision] })]);

export const p0Executions = sqliteTable("p0_executions", {
  executionId: text("execution_id").primaryKey(),
  userKey: text("user_key").notNull(),
  accountKey: text("account_key").notNull(),
  status: text("status").notNull(),
  campaignId: text("campaign_id"),
  projectionJson: text("projection_json").notNull(),
  resultJson: text("result_json").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
});

export const p0AccountLocks = sqliteTable("p0_account_locks", {
  accountKey: text("account_key").primaryKey(),
  executionId: text("execution_id").notNull(),
  ownerKey: text("owner_key").notNull(),
  expiresAt: text("expires_at").notNull(),
});
