import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const p0States = sqliteTable("p0_state", {
  userKey: text("user_key").primaryKey(),
  revision: integer("revision").notNull().default(0),
  updatedAt: text("updated_at").notNull(),
  valueJson: text("value_json").notNull(),
});
