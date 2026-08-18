import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { BorderedLoader, DynamicBorder } from "@earendil-works/pi-coding-agent";
import { Container, type SelectItem, SelectList, Text } from "@earendil-works/pi-tui";
import {
	takeTaskPrompt,
	unblockedTickets,
	ticketType,
	type IssueState,
	type WayfinderIssue,
	type WayfinderTicket,
} from "./model.ts";

interface RawGitHubIssue {
	number: number;
	title: string;
	state: string;
	html_url?: string;
	url?: string;
	assignees?: Array<{ login?: string } | string>;
	labels?: Array<{ name?: string } | string>;
}

interface AvailableTask {
	map: WayfinderIssue;
	ticket: WayfinderTicket;
}

const GH_TIMEOUT_MS = 20_000;

function normalizeIssue(issue: RawGitHubIssue): WayfinderIssue {
	const state: IssueState = issue.state.toLowerCase() === "closed" ? "closed" : "open";
	return {
		number: issue.number,
		title: issue.title,
		url: issue.html_url || issue.url || "",
		state,
		assignees: (issue.assignees || [])
			.map((assignee) => (typeof assignee === "string" ? assignee : assignee.login || ""))
			.filter(Boolean),
		labels: (issue.labels || [])
			.map((label) => (typeof label === "string" ? label : label.name || ""))
			.filter(Boolean),
	};
}

async function ghText(
	pi: ExtensionAPI,
	cwd: string,
	args: string[],
	signal?: AbortSignal,
): Promise<string> {
	const result = await pi.exec("gh", args, { cwd, signal, timeout: GH_TIMEOUT_MS });
	if (result.code !== 0) {
		const details = result.stderr.trim() || result.stdout.trim() || `exit code ${result.code}`;
		throw new Error(details);
	}
	return result.stdout.trim();
}

async function ghJson<T>(
	pi: ExtensionAPI,
	cwd: string,
	args: string[],
	signal?: AbortSignal,
): Promise<T> {
	const text = await ghText(pi, cwd, args, signal);
	try {
		return JSON.parse(text) as T;
	} catch {
		throw new Error(`Некорректный JSON от gh ${args.join(" ")}`);
	}
}

async function resolveRepo(pi: ExtensionAPI, cwd: string, signal?: AbortSignal): Promise<string> {
	const repo = await ghText(pi, cwd, ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], signal);
	if (!/^[^/]+\/[^/]+$/.test(repo)) throw new Error("Не удалось определить GitHub-репозиторий.");
	return repo;
}

async function listMaps(
	pi: ExtensionAPI,
	cwd: string,
	repo: string,
	signal?: AbortSignal,
): Promise<WayfinderIssue[]> {
	const maps = await ghJson<RawGitHubIssue[]>(
		pi,
		cwd,
		[
			"issue",
			"list",
			"--repo",
			repo,
			"--state",
			"open",
			"--label",
			"wayfinder:map",
			"--limit",
			"100",
			"--json",
			"number,title,url,state,assignees,labels",
		],
		signal,
	);
	return maps.map(normalizeIssue);
}

async function listSubIssues(
	pi: ExtensionAPI,
	cwd: string,
	repo: string,
	mapNumber: number,
	signal?: AbortSignal,
): Promise<WayfinderIssue[]> {
	const issues = await ghJson<RawGitHubIssue[]>(
		pi,
		cwd,
		["api", `repos/${repo}/issues/${mapNumber}/sub_issues?per_page=100`],
		signal,
	);
	return issues.map(normalizeIssue);
}

async function listBlockers(
	pi: ExtensionAPI,
	cwd: string,
	repo: string,
	ticketNumber: number,
	signal?: AbortSignal,
): Promise<WayfinderIssue[]> {
	const issues = await ghJson<RawGitHubIssue[]>(
		pi,
		cwd,
		["api", `repos/${repo}/issues/${ticketNumber}/dependencies/blocked_by?per_page=100`],
		signal,
	);
	return issues.map(normalizeIssue);
}

async function loadAvailableTasks(
	pi: ExtensionAPI,
	cwd: string,
	signal?: AbortSignal,
): Promise<AvailableTask[]> {
	const repo = await resolveRepo(pi, cwd, signal);
	const maps = await listMaps(pi, cwd, repo, signal);
	const groups = await Promise.all(
		maps.map(async (map) => {
			const children = await listSubIssues(pi, cwd, repo, map.number, signal);
			const candidates = children.filter((ticket) => ticket.state === "open");
			const tickets = await Promise.all(
				candidates.map(async (ticket): Promise<WayfinderTicket> => ({
					...ticket,
					blockers: await listBlockers(pi, cwd, repo, ticket.number, signal),
				})),
			);
			return unblockedTickets(tickets).map((ticket) => ({ map, ticket }));
		}),
	);
	return groups.flat();
}

async function showTaskPicker(
	ctx: ExtensionCommandContext,
	tasks: AvailableTask[],
): Promise<AvailableTask | undefined> {
	const items: SelectItem[] = tasks.map(({ map, ticket }) => ({
		value: `${map.number}:${ticket.number}`,
		label: ticket.title,
		description: `${ticketType(ticket)} · ${map.title}`,
	}));

	const selected = await ctx.ui.custom<string | null>(
		(tui, theme, _keybindings, done) => {
			const container = new Container();
			container.addChild(new DynamicBorder((text: string) => theme.fg("accent", text)));
			container.addChild(new Text(theme.fg("accent", theme.bold("◆ Незаблокированные задачи Wayfinder")), 1, 0));
			container.addChild(new Text(theme.fg("muted", `${tasks.length} незаблокировано`), 1, 0));

			const list = new SelectList(items, Math.min(items.length, 12), {
				selectedPrefix: (text) => theme.fg("accent", text),
				selectedText: (text) => theme.fg("accent", text),
				description: (text) => theme.fg("muted", text),
				scrollInfo: (text) => theme.fg("dim", text),
				noMatch: (text) => theme.fg("warning", text),
			});
			list.onSelect = (item) => done(item.value);
			list.onCancel = () => done(null);
			container.addChild(list);
			container.addChild(new Text(theme.fg("dim", "↑↓ выбрать · Enter взять в работу · Esc закрыть"), 1, 0));
			container.addChild(new DynamicBorder((text: string) => theme.fg("accent", text)));

			return {
				render: (width: number) => container.render(width),
				invalidate: () => container.invalidate(),
				handleInput: (data: string) => {
					list.handleInput(data);
					tui.requestRender();
				},
			};
		},
		{
			overlay: true,
			overlayOptions: { width: "80%", minWidth: 72, maxHeight: "80%", anchor: "center", margin: 1 },
		},
	);

	return selected
		? tasks.find(({ map, ticket }) => `${map.number}:${ticket.number}` === selected)
		: undefined;
}

export default function wayfinderPicker(pi: ExtensionAPI): void {
	pi.registerCommand("wf", {
		description: "Выбрать доступную задачу Wayfinder",
		handler: async (_args, ctx) => {
			if (ctx.mode !== "tui") {
				ctx.ui.notify("/wf доступен только в интерактивном режиме Pi.", "error");
				return;
			}

			let failure: unknown;
			const tasks = await ctx.ui.custom<AvailableTask[] | null>((tui, theme, _keybindings, done) => {
				const loader = new BorderedLoader(tui, theme, "Загружаю доступные задачи Wayfinder…");
				loader.onAbort = () => done(null);
				void loadAvailableTasks(pi, ctx.cwd, loader.signal)
					.then(done)
					.catch((error) => {
						if (loader.signal.aborted) return;
						failure = error;
						done(null);
					});
				return loader;
			});

			if (failure) {
				ctx.ui.notify(`Wayfinder: ${failure instanceof Error ? failure.message : String(failure)}`, "error");
				return;
			}
			if (!tasks) return;
			if (tasks.length === 0) {
				ctx.ui.notify("Нет открытых незаблокированных задач Wayfinder.", "info");
				return;
			}

			const choice = await showTaskPicker(ctx, tasks);
			if (!choice) return;

			pi.sendUserMessage(takeTaskPrompt(choice.ticket.url), {
				expandPromptTemplates: true,
			});
		},
	});
}
