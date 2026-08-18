import assert from "node:assert/strict";
import test from "node:test";
import {
	isUnblockedTicket,
	takeTaskPrompt,
	ticketType,
	unblockedTickets,
	type WayfinderIssue,
	type WayfinderTicket,
} from "./model.ts";

const map: WayfinderIssue = {
	number: 51,
	title: "Спецификация Автономного оператора кампаний",
	url: "https://github.com/ElJeskos/MOX-ADV/issues/51",
	state: "open",
	assignees: [],
	labels: ["wayfinder:map"],
};

function ticket(overrides: Partial<WayfinderTicket> = {}): WayfinderTicket {
	return {
		number: 63,
		title: "Как должен ощущаться цикл от рекламной стратегии до автономного управления?",
		url: "https://github.com/ElJeskos/MOX-ADV/issues/63",
		state: "open",
		assignees: [],
		labels: ["wayfinder:prototype"],
		blockers: [],
		...overrides,
	};
}

test("list contains every open ticket without an open blocker regardless of assignee", () => {
	const free = ticket();
	const assigned = ticket({ number: 64, assignees: ["ElJeskos"] });
	const blocked = ticket({
		number: 65,
		blockers: [{ ...map, number: 56, title: "Blocker", state: "open" }],
	});
	const closed = ticket({ number: 66, state: "closed" });
	const closedBlocker = ticket({
		number: 67,
		blockers: [{ ...map, number: 52, title: "Resolved research", state: "closed" }],
	});

	assert.equal(isUnblockedTicket(free), true);
	assert.equal(isUnblockedTicket(assigned), true);
	assert.equal(isUnblockedTicket(blocked), false);
	assert.equal(isUnblockedTicket(closed), false);
	assert.equal(isUnblockedTicket(closedBlocker), true);
	assert.deepEqual(unblockedTickets([free, assigned, blocked, closed, closedBlocker]).map((item) => item.number), [63, 64, 67]);
});

test("ticket type comes from the Wayfinder label", () => {
	assert.equal(ticketType(ticket()), "prototype");
	assert.equal(ticketType(ticket({ labels: [] })), "task");
});

test("selection continues with the compact Wayfinder prompt", () => {
	assert.equal(
		takeTaskPrompt("https://github.com/ElJeskos/MOX-ADV/issues/63"),
		"/wayfinder возьми в работу задачу https://github.com/ElJeskos/MOX-ADV/issues/63",
	);
});
