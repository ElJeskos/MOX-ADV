export type IssueState = "open" | "closed";

export interface WayfinderIssue {
	number: number;
	title: string;
	url: string;
	state: IssueState;
	assignees: string[];
	labels: string[];
}

export interface WayfinderTicket extends WayfinderIssue {
	blockers: WayfinderIssue[];
}

export function isUnblockedTicket(ticket: WayfinderTicket): boolean {
	return ticket.state === "open" && !ticket.blockers.some((blocker) => blocker.state === "open");
}

export function unblockedTickets(tickets: WayfinderTicket[]): WayfinderTicket[] {
	return tickets.filter(isUnblockedTicket);
}

export function ticketType(ticket: WayfinderIssue): string {
	const label = ticket.labels.find((candidate) => candidate.startsWith("wayfinder:") && candidate !== "wayfinder:map");
	return label?.slice("wayfinder:".length) || "task";
}

export function takeTaskPrompt(issueUrl: string): string {
	return `/wayfinder возьми в работу задачу ${issueUrl}`;
}
