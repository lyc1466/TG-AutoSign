"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getToken } from "../../../lib/auth";
import {
    listSignTasks,
    deleteSignTask,
    runSignTask,
    getSignTaskStatus,
    getSignTaskHistory,
    getSignTaskMonitorWebSocketUrl,
    listAccounts,
    SignTask,
    SignTaskHistoryItem,
    SignTaskMessageEvent,
    SignTaskMonitorStreamEvent,
    AccountInfo,
} from "../../../lib/api";
import {
    Plus,
    CaretLeft,
    Play,
    PencilSimple,
    Trash,
    Spinner,
    Lightning,
    Clock,
    ChatCircleText,
    ListDashes,
    ArrowClockwise,
    X,
} from "@phosphor-icons/react";
import { ToastContainer, useToast } from "../../../components/ui/toast";
import { ThemeLanguageToggle } from "../../../components/ThemeLanguageToggle";
import { useLanguage } from "../../../context/LanguageContext";

const truncateSummaryText = (text: string, limit = 200) => {
    if (text.length <= limit) return text;
    return `${text.slice(0, limit - 3)}...`;
};

const getMessageEventKey = (event: SignTaskMessageEvent) => {
    if (event.chat_id !== undefined && event.chat_id !== null && event.message_id !== undefined && event.message_id !== null) {
        return `${event.chat_id}:${event.message_id}`;
    }
    const eventId = String(event.event_id || "").trim();
    if (!eventId) return "";
    const parts = eventId.split(":", 4);
    if (parts.length >= 3 && parts[1] && parts[2]) {
        return `${parts[1]}:${parts[2]}`;
    }
    return eventId;
};

const getIncomingMessageSummaries = (events: SignTaskMessageEvent[]) => {
    const replies: string[] = [];
    const replyPositions = new Map<string, number>();

    for (const event of events) {
        const eventType = String(event.event_type || "").trim().toLowerCase();
        if (eventType && eventType !== "message_received" && eventType !== "message_edited") {
            continue;
        }
        if (event.is_outgoing || event.sender?.is_self) {
            continue;
        }
        const summary = String(event.summary || event.text || event.caption || "").trim();
        if (!summary) {
            continue;
        }
        const clippedSummary = truncateSummaryText(summary);
        const eventKey = getMessageEventKey(event);
        if (eventKey && replyPositions.has(eventKey)) {
            replies[replyPositions.get(eventKey)!] = clippedSummary;
        } else if (eventKey) {
            replyPositions.set(eventKey, replies.length);
            replies.push(clippedSummary);
        } else {
            replies.push(clippedSummary);
        }
    }

    return replies;
};

const summarizeIncomingMessages = (
    events: SignTaskMessageEvent[],
    language: string,
) => {
    const replies = getIncomingMessageSummaries(events);

    if (replies.length === 0) {
        return "";
    }

    const summary = language === "zh"
        ? `收到 ${replies.length} 条回复，最后一条：${replies[replies.length - 1]}`
        : `Received ${replies.length} replies, last message: ${replies[replies.length - 1]}`;

    return truncateSummaryText(summary);
};

export default function SignTasksPage() {
    const router = useRouter();
    const { t, language } = useLanguage();
    const { toasts, addToast, removeToast } = useToast();
    const [token, setLocalToken] = useState<string | null>(null);
    const [tasks, setTasks] = useState<SignTask[]>([]);
    const [accounts, setAccounts] = useState<AccountInfo[]>([]);
    const [loading, setLoading] = useState(false);
    const [checking, setChecking] = useState(true);
    const [runningTask, setRunningTask] = useState<{ name: string; accountName: string } | null>(null);
    const [runLogs, setRunLogs] = useState<string[]>([]);
    const [runMessages, setRunMessages] = useState<SignTaskMessageEvent[]>([]);
    const [runMonitorTab, setRunMonitorTab] = useState<"logs" | "messages">("logs");
    const [runResult, setRunResult] = useState<{ accepted?: boolean; success: boolean; output: string; error: string; status?: string; status_text?: string; phase?: string; phase_text?: string; message?: string } | null>(null);
    const [runStatus, setRunStatus] = useState<any | null>(null);
    const [isDone, setIsDone] = useState(false);
    const [historyTask, setHistoryTask] = useState<SignTask | null>(null);
    const [historyLogs, setHistoryLogs] = useState<SignTaskHistoryItem[]>([]);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyTab, setHistoryTab] = useState<"messages" | "logs">("messages");
    const runSocketRef = useRef<WebSocket | null>(null);
    const runResultRef = useRef<{ accepted?: boolean; success: boolean; output: string; error: string; status?: string; status_text?: string; phase?: string; phase_text?: string; message?: string } | null>(null);

    const addToastRef = useRef(addToast);
    const tRef = useRef(t);

    useEffect(() => {
        addToastRef.current = addToast;
        tRef.current = t;
    }, [addToast, t]);

    const formatErrorMessage = useCallback((key: string, err?: any) => {
        const base = tRef.current ? tRef.current(key) : key;
        const code = err?.code;
        return code ? `${base} (${code})` : base;
    }, []);

    const closeRunMonitor = useCallback(() => {
        if (runSocketRef.current) {
            runSocketRef.current.close();
            runSocketRef.current = null;
        }
        setRunningTask(null);
        setRunLogs([]);
        setRunMessages([]);
        setRunResult(null);
        setRunStatus(null);
        runResultRef.current = null;
        setRunMonitorTab("logs");
        setIsDone(false);
    }, []);

    const loadData = useCallback(async (tokenStr: string) => {
        try {
            setLoading(true);
            const [tasksData, accountsData] = await Promise.all([
                listSignTasks(tokenStr),
                listAccounts(tokenStr),
            ]);
            setTasks(tasksData);
            setAccounts(accountsData.accounts);
        } catch (err: any) {
            const toast = addToastRef.current;
            if (toast) {
                toast(formatErrorMessage("load_failed", err), "error");
            }
        } finally {
            setLoading(false);
        }
    }, [formatErrorMessage]);

    useEffect(() => {
        const tokenStr = getToken();
        if (!tokenStr) {
            window.location.replace("/");
            return;
        }
        setLocalToken(tokenStr);
        setChecking(false);
        loadData(tokenStr);
    }, [loadData]);

    useEffect(() => {
        return () => {
            if (runSocketRef.current) {
                runSocketRef.current.close();
                runSocketRef.current = null;
            }
        };
    }, []);

    const handleDelete = async (task: SignTask) => {
        if (!token) return;

        if (!confirm(t("confirm_delete"))) {
            return;
        }

        try {
            setLoading(true);
            await deleteSignTask(token, task.name, task.account_name);
            addToast(t("task_deleted").replace("{name}", task.name), "success");
            await loadData(token);
        } catch (err: any) {
            addToast(formatErrorMessage("delete_failed", err), "error");
        } finally {
            setLoading(false);
        }
    };

    const handleRun = async (task: SignTask) => {
        if (!token) return;

        const accountName = task.account_name || prompt(t("account_name_prompt"));
        if (!accountName) return;

        try {
            setLoading(true);
            setRunningTask({ name: task.name, accountName });
            setRunLogs([]);
            setRunMessages([]);
            setRunResult(null);
            setRunStatus(null);
            runResultRef.current = null;
            setRunMonitorTab("logs");
            setIsDone(false);

            if (runSocketRef.current) {
                runSocketRef.current.close();
            }
            const ws = new WebSocket(
                getSignTaskMonitorWebSocketUrl(token, task.name, accountName)
            );
            runSocketRef.current = ws;

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data) as SignTaskMonitorStreamEvent;
                if (data.type === "logs") {
                    setRunLogs(prev => [...prev, ...data.data]);
                } else if (data.type === "message_events") {
                    setRunMessages(prev => [...prev, ...data.data]);
                } else if (data.type === "done") {
                    setIsDone(true);
                    if (runSocketRef.current === ws) {
                        runSocketRef.current = null;
                    }
                }
            };

            ws.onclose = () => {
                if (runSocketRef.current === ws) {
                    runSocketRef.current = null;
                    if (runResultRef.current) {
                        setIsDone(true);
                    }
                }
            };

            ws.onerror = (err) => {
                console.error("WebSocket error:", err);
            };

            const result = await runSignTask(token, task.name, accountName);
            setRunResult(result);
            setRunStatus(result);
            runResultRef.current = result;

            if (!result.success) {
                if (result.error && result.error.includes("运行中")) {
                    addToast(language === "zh" ? "该任务正在运行中，无法重复开始。正在为您展示其实时进度..." : "Task is currently running. Real-time logs are shown below.", "info");
                } else {
                    addToast(result.error || t("task_run_failed"), "error");
                    setIsDone(true);
                }
            } else {
                const submittedMessage = result.message || (language === "zh" ? "任务已提交后台执行" : "Task submitted to run in the background");
                addToast(submittedMessage, "success");
                if (!runSocketRef.current) {
                    setIsDone(true);
                }
            }
        } catch (err: any) {
            if (err?.status === 409) {
                addToast(err.message || (language === "zh" ? "该任务正在执行中，请勿重复触发" : "Task is already running."), "info");
                setRunResult({
                    accepted: false,
                    success: false,
                    output: "",
                    error: err.message || "",
                    status: "running",
                    status_text: language === "zh" ? "任务正在执行中" : "Task is running",
                    message: err.message || "",
                });
                setRunStatus((prev: any) => prev || {
                    status: "running",
                    status_text: language === "zh" ? "任务正在执行中" : "Task is running",
                    message: err.message || "",
                    is_running: true,
                });
            } else {
                addToast(err?.message || formatErrorMessage("task_run_failed", err), "error");
                if (runSocketRef.current) {
                    runSocketRef.current.close();
                    runSocketRef.current = null;
                }
                setIsDone(true);
            }
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!token || !runningTask || isDone) return;
        let cancelled = false;
        const poll = async () => {
            try {
                const status = await getSignTaskStatus(token, runningTask.name, runningTask.accountName);
                if (cancelled) return;
                setRunStatus(status);
                if (Array.isArray(status.logs) && status.logs.length > 0) {
                    setRunLogs(status.logs);
                }
                if (Array.isArray(status.message_events)) {
                    setRunMessages(status.message_events);
                }
                if (!status.is_running && ["completed", "failed"].includes(status.status)) {
                    setIsDone(true);
                    if (status.status === "completed") {
                        addToast(language === "zh" ? "任务已完成，可在历史中查看链式日志" : "Task completed. History is available.", "success");
                    } else if (status.message || status.error) {
                        addToast(status.message || status.error, "error");
                    }
                }
            } catch {
                // WebSocket remains the primary live channel; polling is best-effort.
            }
        };
        poll();
        const timer = window.setInterval(poll, 1000);
        return () => {
            cancelled = true;
            window.clearInterval(timer);
        };
    }, [token, runningTask, isDone, addToast, language]);

    const handleShowTaskHistory = async (task: SignTask) => {
        if (!token) return;
        setHistoryTask(task);
        setHistoryLogs([]);
        setHistoryLoading(true);
        try {
            const logs = await getSignTaskHistory(token, task.name, task.account_name, 30);
            setHistoryLogs(logs);
            setHistoryTab(
                logs.some((item) => (item.message_events?.length || 0) > 0)
                    ? "messages"
                    : "logs"
            );
        } catch (err: any) {
            addToast(formatErrorMessage("logs_fetch_failed", err), "error");
        } finally {
            setHistoryLoading(false);
        }
    };

    const formatPartyLabel = (
        party?: { id?: number | null; username?: string; display_name?: string },
        fallback?: { id?: number | null; username?: string; display_name?: string },
        emptyLabel?: string,
    ) => {
        const id = party?.id ?? fallback?.id;
        const displayName = String(party?.display_name || fallback?.display_name || "").trim();
        const username = String(party?.username || fallback?.username || "").trim().replace(/^@/, "");

        if (displayName && username && id !== undefined && id !== null) {
            return `${displayName} (@${username}, ${id})`;
        }
        if (displayName && id !== undefined && id !== null && displayName !== String(id)) {
            return `${displayName} (${id})`;
        }
        if (username && id !== undefined && id !== null) {
            return `@${username} (${id})`;
        }
        if (displayName) return displayName;
        if (username) return `@${username}`;
        if (id !== undefined && id !== null) return String(id);
        return emptyLabel || t("unknown_sender");
    };

    const describeMessageEvent = (event: SignTaskMessageEvent) => {
        const senderName = formatPartyLabel(event.sender, undefined, t("unknown_sender"));
        const recipientName = formatPartyLabel(
            event.recipient,
            {
                id: event.chat_id,
                username: event.chat_username,
                display_name: event.chat_title,
            },
            t("unknown_chat"),
        );
        const body = event.text || event.caption || event.summary || t("task_monitor_no_messages");
        const typeLabel = event.event_type === "message_sent"
            ? t("task_message_event_sent")
            : event.event_type === "message_edited"
                ? t("task_message_event_edited")
                : t("task_message_event_received");

        return {
            senderName: String(senderName),
            recipientName: String(recipientName),
            body,
            typeLabel,
        };
    };

    const latestRunSummary = (() => {
        const replySummary = summarizeIncomingMessages(runMessages, language);
        if (replySummary) return replySummary;
        if (runStatus?.message) return runStatus.message;
        if (runStatus?.last_log) return runStatus.last_log;
        if (runResult?.error) return runResult.error;
        if (runResult?.success && runLogs.length > 0) return runLogs[runLogs.length - 1];
        return t("logs_waiting");
    })();

    if (!token || checking) {
        return null;
    }

    return (
        <div id="tasks-view" className="w-full h-full flex flex-col">
            <nav className="navbar">
                <div className="nav-brand">
                    <div className="flex items-center gap-4">
                        <Link href="/dashboard" className="action-btn !w-8 !h-8" title={t("sidebar_home")}>
                            <CaretLeft weight="bold" size={18} />
                        </Link>
                        <h1 className="text-lg font-bold tracking-tight">{t("sidebar_tasks")}</h1>
                    </div>
                </div>
                <div className="top-right-actions">
                    <button
                        onClick={() => loadData(token)}
                        disabled={loading}
                        className="action-btn !w-8 !h-8"
                        title={t("refresh_list")}
                    >
                        <ArrowClockwise weight="bold" size={18} className={loading ? 'animate-spin' : ''} />
                    </button>
                    <Link
                        href="/dashboard/sign-tasks/create"
                        className={`action-btn !w-8 !h-8 !text-[#8a3ffc] hover:bg-[#8a3ffc]/10 ${loading ? 'pointer-events-none opacity-20' : ''}`}
                        title={t("add_task")}
                    >
                        <Plus weight="bold" size={18} />
                    </Link>
                </div>
            </nav>

            <main className="main-content !pt-6">

                {loading && tasks.length === 0 ? (
                    <div className="w-full py-20 flex flex-col items-center justify-center text-main/20">
                        <Spinner size={40} weight="bold" className="animate-spin mb-4" />
                        <p className="text-xs uppercase tracking-widest font-bold font-mono">{t("login_loading")}</p>
                    </div>
                ) : tasks.length === 0 ? (
                    <div className="glass-panel p-20 flex flex-col items-center text-center justify-center border-dashed border-2 group hover:border-[#8a3ffc]/30 transition-all cursor-pointer" onClick={() => router.push("/dashboard/sign-tasks/create")}>
                        <div className="w-20 h-20 rounded-3xl bg-main/5 flex items-center justify-center text-main/20 mb-6 group-hover:scale-110 transition-transform group-hover:bg-[#8a3ffc]/10 group-hover:text-[#8a3ffc]">
                            <Plus size={40} weight="bold" />
                        </div>
                        <h3 className="text-xl font-bold mb-2">{t("no_tasks")}</h3>
                        <p className="text-sm text-[#9496a1] mb-8">{t("no_tasks_desc")}</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                        {tasks.map((task) => (
                            <div key={task.name} className="flex flex-col gap-3">
                                <div className="glass-panel p-4 sm:hidden">
                                    <div className="grid grid-cols-[1fr_auto] gap-3">
                                        <div className="min-w-0 space-y-2">
                                            <div className="flex items-center gap-2">
                                                <div className="w-6 h-6 rounded-lg bg-[#8a3ffc]/20 flex items-center justify-center text-[#b57dff] shrink-0">
                                                    <Lightning weight="fill" size={12} />
                                                </div>
                                                <span className="font-bold text-sm truncate" title={task.name}>{task.name}</span>
                                                <span className="text-[9px] font-mono text-main/30 bg-white/5 px-1.5 py-0.5 rounded border border-white/5 shrink-0">
                                                    {task.chats[0]?.chat_id || "-"}
                                                </span>
                                            </div>
                                            <span className="text-[11px] font-mono text-main/50">
                                                {task.execution_mode === "range" && task.range_start && task.range_end
                                                    ? `${task.range_start} - ${task.range_end}`
                                                    : task.sign_at}
                                            </span>
                                            <div className="space-y-1 pt-2">
                                                <span className={`inline-flex text-[9px] font-bold px-2 py-0.5 rounded-full uppercase tracking-widest border ${task.enabled ? 'status-badge-success' : 'status-badge-neutral'}`}>
                                                    {task.enabled ? t("status_active") : t("status_paused")}
                                                </span>
                                                {task.last_run ? (
                                                    <div className="text-[10px] font-mono ui-muted flex items-center gap-2">
                                                        <span className={task.last_run.success ? 'status-text-success' : 'status-text-danger'}>
                                                            {task.last_run.success ? t("success") : t("failure")}
                                                        </span>
                                                        <span>
                                                            {new Date(task.last_run.time).toLocaleString(undefined, {
                                                                month: '2-digit',
                                                                day: '2-digit',
                                                                hour: '2-digit',
                                                                minute: '2-digit'
                                                            })}
                                                        </span>
                                                    </div>
                                                ) : null}
                                            </div>
                                        </div>
                                        <div className="w-14 flex flex-col items-center gap-2 pt-[2px]">
                                            <button
                                                onClick={() => handleRun(task)}
                                                disabled={loading}
                                                className="action-btn !w-11 !h-11 status-action-success disabled:opacity-20 disabled:cursor-not-allowed"
                                                title={t("run")}
                                            >
                                                <Play weight="fill" size={14} />
                                            </button>
                                            <Link
                                                href={`/dashboard/account-tasks/AccountTasksContent?name=${task.account_name}`}
                                                className={`action-btn !w-11 !h-11 ${loading ? 'pointer-events-none opacity-20' : ''}`}
                                                title={t("edit")}
                                            >
                                                <PencilSimple weight="bold" size={14} />
                                            </Link>
                                            <button
                                                onClick={() => handleShowTaskHistory(task)}
                                                disabled={loading}
                                                className="action-btn !w-11 !h-11 !text-[#8a3ffc] hover:bg-[#8a3ffc]/10 disabled:opacity-20 disabled:cursor-not-allowed"
                                                title={t("task_history_logs")}
                                            >
                                                <ListDashes weight="bold" size={14} />
                                            </button>
                                            <button
                                                onClick={() => handleDelete(task)}
                                                disabled={loading}
                                                className="action-btn !w-11 !h-11 status-action-danger disabled:opacity-20 disabled:cursor-not-allowed"
                                                title={t("delete")}
                                            >
                                                <Trash weight="bold" size={14} />
                                            </button>
                                        </div>
                                    </div>
                                </div>
                                <div className="glass-panel p-6 hidden sm:flex flex-col group hover:border-[#8a3ffc]/40 transition-all">
                                <div className="flex justify-between items-start mb-6">
                                    <div className="flex items-center gap-4">
                                        <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-[#8a3ffc]/20 to-[#e83ffc]/20 flex items-center justify-center text-[#b57dff] group-hover:scale-110 transition-transform">
                                            <Lightning weight="fill" size={24} />
                                        </div>
                                        <div className="min-w-0">
                                            <h3 className="font-bold text-lg truncate pr-2" title={task.name}>{task.name}</h3>
                                            <div className="flex items-center gap-2 mt-1">
                                                <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full uppercase tracking-widest border ${task.enabled ? 'status-badge-success' : 'status-badge-neutral'}`}>
                                                    {task.enabled ? t("status_active") : t("status_paused")}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div className="space-y-4 mb-8">
                                    <div className="flex items-center justify-between p-3 bg-white/2 rounded-xl border border-white/5">
                                        <div className="flex items-center gap-2 text-main/60">
                                            <Clock weight="bold" size={14} />
                                            <span className="text-[10px] font-bold uppercase tracking-wider">{t("task_schedule")}</span>
                                        </div>
                                        <span className="text-xs font-mono font-bold text-[#b57dff]">{task.sign_at}</span>
                                    </div>
                                    <div className="flex items-center justify-between p-3 bg-white/2 rounded-xl border border-white/5">
                                        <div className="flex items-center gap-2 text-main/60">
                                            <ChatCircleText weight="bold" size={14} />
                                            <span className="text-[10px] font-bold uppercase tracking-wider">{t("task_channels")}</span>
                                        </div>
                                        <span className="text-xs font-mono font-bold text-[#e83ffc]">
                                            {t("task_hits").replace("{count}", task.chats.length.toString())}
                                        </span>
                                    </div>
                                    <div className="flex items-center justify-between p-3 bg-white/2 rounded-xl border border-white/5">
                                        <div className="flex items-center gap-2 text-main/60">
                                            <ArrowClockwise weight="bold" size={14} />
                                            <span className="text-[10px] font-bold uppercase tracking-wider">{t("task_last_run")}</span>
                                        </div>
                                        {task.last_run ? (
                                            <span className={`text-xs font-mono font-bold ${task.last_run.success ? 'status-text-success' : 'status-text-danger'}`}>
                                                {task.last_run.success ? t("success") : t("failure")} · {new Date(task.last_run.time).toLocaleString(language === "zh" ? 'zh-CN' : 'en-US', {
                                                    month: '2-digit',
                                                    day: '2-digit',
                                                    hour: '2-digit',
                                                    minute: '2-digit'
                                                })}
                                            </span>
                                        ) : (
                                            <span className="text-xs font-mono font-bold text-main/50">{t("no_data")}</span>
                                        )}
                                    </div>
                                </div>

                                <div className="mt-auto flex items-center justify-between bg-black/10 -mx-6 -mb-6 p-4 border-t border-white/5">
                                    <div className="flex items-center gap-2">
                                        <button
                                            onClick={() => handleRun(task)}
                                            disabled={loading}
                                            className="action-btn status-action-success disabled:opacity-20 disabled:cursor-not-allowed"
                                            title={t("run")}
                                        >
                                            <Play weight="fill" />
                                        </button>
                                        <Link
                                            href={`/dashboard/account-tasks/AccountTasksContent?name=${task.account_name}`}
                                            className={`action-btn ${loading ? 'pointer-events-none opacity-20' : ''}`}
                                            title={t("edit")}
                                        >
                                            <PencilSimple weight="bold" />
                                        </Link>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <button
                                            onClick={() => handleShowTaskHistory(task)}
                                            disabled={loading}
                                            className="action-btn !text-[#8a3ffc] hover:bg-[#8a3ffc]/10 disabled:opacity-20 disabled:cursor-not-allowed"
                                            title={t("task_history_logs")}
                                        >
                                            <ListDashes weight="bold" />
                                        </button>
                                        <button
                                            onClick={() => handleDelete(task)}
                                            disabled={loading}
                                            className="action-btn status-action-danger disabled:opacity-20 disabled:cursor-not-allowed"
                                            title={t("delete")}
                                        >
                                            <Trash weight="bold" />
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        ))}
                    </div>
                )}
            </main>

            <ToastContainer toasts={toasts} removeToast={removeToast} />

            {/* 运行监控 Modal */}
            {runningTask && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-sm animate-fade-in">
                    <div className="glass-panel w-full max-w-5xl h-[78vh] flex flex-col shadow-2xl border border-white/10 overflow-hidden animate-zoom-in">
                        <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/2">
                            <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-lg bg-[#8a3ffc]/20 flex items-center justify-center text-[#b57dff]">
                                    {isDone ? <Lightning weight="fill" size={18} /> : <Spinner weight="bold" size={18} className="animate-spin" />}
                                </div>
                                <div>
                                    <h3 className="font-bold tracking-tight">
                                        {t("task_monitor_title").replace("{name}", runningTask.name)}
                                    </h3>
                                    <span className={`text-[10px] font-bold uppercase tracking-wider ${isDone ? "status-text-success" : "text-[#8a3ffc] animate-pulse"}`}>
                                        {isDone ? t("task_done") : t("task_running")}
                                    </span>
                                </div>
                            </div>
                            <button
                                onClick={closeRunMonitor}
                                className="action-btn !w-8 !h-8 hover:bg-white/10"
                            >
                                <X weight="bold" />
                            </button>
                        </div>
                        <div className="p-4 border-b border-white/5 bg-black/10">
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                                    <div className="text-main/40 uppercase tracking-wider mb-1">{t("task_monitor_status")}</div>
                                    <div className={`font-bold ${runResult && !runResult.success ? "status-text-danger" : isDone ? "status-text-success" : "text-[#b57dff]"}`}>
                                        {runStatus?.status_text || runStatus?.phase_text || (runResult && !runResult.success ? t("failure") : isDone ? t("success") : t("task_running"))}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                                    <div className="text-main/40 uppercase tracking-wider mb-1">{t("associated_account")}</div>
                                    <div className="font-mono text-main/80 break-all">{runningTask.accountName}</div>
                                </div>
                                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                                    <div className="text-main/40 uppercase tracking-wider mb-1">{t("task_monitor_summary")}</div>
                                    <div className="text-main/80 break-all">{latestRunSummary}</div>
                                </div>
                            </div>
                            {runStatus?.status === "waiting_account_lock" && (
                                <div className="mt-3 rounded-xl border border-amber-400/20 bg-amber-400/10 p-3 text-xs text-main/80">
                                    <div className="font-bold text-amber-200">正在等待账号空闲</div>
                                    <div>前序任务：{runStatus.blocking_task_name || "未知"}</div>
                                    <div>前序阶段：{runStatus.blocking_phase_text || "未知"}</div>
                                    <div>最后进度：{runStatus.blocking_last_log || runStatus.last_log || "等待前序任务更新"}</div>
                                </div>
                            )}
                            {runStatus?.phase === "waiting_reply" && (
                                <div className="mt-3 rounded-xl border border-[#8a3ffc]/20 bg-[#8a3ffc]/10 p-3 text-xs text-main/80">
                                    <div className="font-bold text-[#d8c2ff]">等待机器人回复</div>
                                    <div>{runStatus.message || runStatus.last_log || "正在等待机器人回复"}</div>
                                </div>
                            )}
                            <div className="flex items-center gap-2 mt-4">
                                <button
                                    onClick={() => setRunMonitorTab("logs")}
                                    className={`px-3 py-1.5 rounded-full border text-xs font-bold transition-all ${runMonitorTab === "logs" ? "border-transparent bg-[#8a3ffc] text-white" : "history-tab-inactive"}`}
                                >
                                    {t("logs")}
                                </button>
                                <button
                                    onClick={() => setRunMonitorTab("messages")}
                                    className={`px-3 py-1.5 rounded-full border text-xs font-bold transition-all ${runMonitorTab === "messages" ? "border-transparent bg-[#8a3ffc] text-white" : "history-tab-inactive"}`}
                                >
                                    {t("task_monitor_messages_tab")} ({runMessages.length})
                                </button>
                            </div>
                        </div>
                        <div className="flex-1 overflow-y-auto p-4 font-mono text-[11px] leading-relaxed history-modal-body">
                            {runMonitorTab === "logs" ? (
                                runLogs.length === 0 ? (
                                    <div className="flex items-center gap-2 ui-muted italic">
                                        <Spinner className="animate-spin" size={12} />
                                        {t("logs_waiting")}
                                    </div>
                                ) : (
                                    <div className="space-y-1">
                                        {runLogs.map((log, i) => (
                                            <div key={i} className="text-main/80 flex gap-2">
                                                <span className="ui-line-number select-none w-6 text-right">{(i + 1).toString().padStart(2, '0')}</span>
                                                <span className="break-all">{log}</span>
                                            </div>
                                        ))}
                                    </div>
                                )
                            ) : runMessages.length === 0 ? (
                                <div className="ui-muted italic">{t("task_monitor_no_messages")}</div>
                            ) : (
                                <div className="space-y-3">
                                    {runMessages.map((event, index) => {
                                        const message = describeMessageEvent(event);
                                        return (
                                            <div
                                                key={event.event_id || `${event.event_time}-${index}`}
                                                className="rounded-xl border history-message-card p-3"
                                            >
                                                <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] mb-2">
                                                    <div className="flex items-center gap-2">
                                                        <span className="px-2 py-0.5 rounded-full bg-[#8a3ffc]/15 text-[#c59bff] border border-[#8a3ffc]/20">
                                                            {message.typeLabel}
                                                        </span>
                                                        <span className="ui-muted">
                                                            {event.event_time ? new Date(event.event_time).toLocaleString(language === "zh" ? "zh-CN" : "en-US") : t("no_data")}
                                                        </span>
                                                    </div>
                                                    <span className="ui-dim">
                                                        {message.senderName} → {message.recipientName}
                                                    </span>
                                                </div>
                                                <div className="text-main/85 break-words whitespace-pre-wrap">
                                                    {message.body}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                        <div className="p-4 border-t border-white/5 bg-white/2 flex justify-end">
                            <button
                                onClick={closeRunMonitor}
                                className="px-6 py-2 rounded-xl font-bold text-xs transition-all btn-gradient shadow-lg"
                            >
                                {t("close")}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {historyTask && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-sm animate-fade-in">
                    <div className="glass-panel w-full max-w-4xl h-[78vh] flex flex-col shadow-2xl border border-white/10 overflow-hidden animate-zoom-in">
                        <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/2">
                            <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-lg bg-[#8a3ffc]/20 flex items-center justify-center text-[#b57dff]">
                                    <ListDashes weight="bold" size={18} />
                                </div>
                                <div className="space-y-2">
                                    <h3 className="font-bold tracking-tight">
                                        {t("task_history_logs_title").replace("{name}", historyTask.name)}
                                    </h3>
                                    <div className="flex items-center gap-2">
                                        <button
                                            type="button"
                                            onClick={() => setHistoryTab("messages")}
                                            className={`px-3 py-1.5 rounded-full border text-xs font-bold transition-all ${historyTab === "messages" ? "border-transparent bg-[#8a3ffc] text-white" : "history-tab-inactive"}`}
                                        >
                                            {t("task_monitor_messages_tab")}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setHistoryTab("logs")}
                                            className={`px-3 py-1.5 rounded-full border text-xs font-bold transition-all ${historyTab === "logs" ? "border-transparent bg-[#8a3ffc] text-white" : "history-tab-inactive"}`}
                                        >
                                            {t("logs")}
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <button
                                onClick={() => setHistoryTask(null)}
                                className="action-btn !w-8 !h-8 hover:bg-white/10"
                            >
                                <X weight="bold" />
                            </button>
                        </div>
                        <div className="flex-1 overflow-y-auto p-4 font-mono text-[11px] leading-relaxed history-modal-body">
                            {historyLoading ? (
                                <div className="flex items-center gap-2 ui-muted italic">
                                    <Spinner className="animate-spin" size={12} />
                                    {t("loading")}
                                </div>
                            ) : historyLogs.length === 0 ? (
                                <div className="ui-muted italic">{t("task_history_empty")}</div>
                            ) : (
                                <div className="space-y-4">
                                    {historyLogs.map((log, i) => (
                                        <details key={`${log.time}-${i}`} className="rounded-xl border history-entry-card overflow-hidden" open={i === 0}>
                                            <summary className="flex flex-wrap justify-between items-center gap-3 px-4 py-3 cursor-pointer list-none">
                                                <div className="min-w-0">
                                                    <div className="ui-muted text-[10px]">
                                                        {new Date(log.time).toLocaleString(language === "zh" ? "zh-CN" : "en-US")}
                                                    </div>
                                                    <div className="text-main/80 break-all mt-1">
                                                        {log.message || t("task_history_no_flow")}
                                                    </div>
                                                </div>
                                                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${log.success ? "status-badge-success" : "status-badge-danger"}`}>
                                                    {log.success ? t("success") : t("failure")}
                                                </span>
                                            </summary>
                                            <div className="px-4 pb-4 border-t border-white/5">
                                                <div className="pt-4 space-y-3">
                                                    {historyTab === "messages" ? (
                                                        <>
                                                            <div className="text-[10px] uppercase tracking-wider ui-muted">
                                                                {t("task_monitor_messages_tab")}
                                                            </div>
                                                            {log.message_events && log.message_events.length > 0 ? (
                                                                <div className="space-y-3">
                                                                    {log.message_events.map((event, eventIndex) => {
                                                                        const message = describeMessageEvent(event);
                                                                        return (
                                                                            <div
                                                                                key={event.event_id || `${log.time}-${eventIndex}`}
                                                                                className="rounded-xl border history-message-card p-3"
                                                                            >
                                                                                <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] mb-2">
                                                                                    <span className="px-2 py-0.5 rounded-full bg-[#8a3ffc]/15 text-[#c59bff] border border-[#8a3ffc]/20">
                                                                                        {message.typeLabel}
                                                                                    </span>
                                                                                    <span className="ui-muted">
                                                                                        {event.event_time ? new Date(event.event_time).toLocaleString(language === "zh" ? "zh-CN" : "en-US") : t("no_data")}
                                                                                    </span>
                                                                                </div>
                                                                                <div className="ui-dim mb-2">
                                                                                {message.senderName} → {message.recipientName}
                                                                                </div>
                                                                                <div className="text-main/85 break-words whitespace-pre-wrap">
                                                                                    {message.body}
                                                                                </div>
                                                                            </div>
                                                                        );
                                                                    })}
                                                                </div>
                                                            ) : (
                                                                <div className="ui-muted italic">{t("task_history_no_messages")}</div>
                                                            )}
                                                        </>
                                                    ) : (
                                                        <>
                                                            <div className="text-[10px] uppercase tracking-wider ui-muted">
                                                                {t("logs")}
                                                            </div>
                                                            {log.flow_logs && log.flow_logs.length > 0 ? (
                                                                <div className="space-y-1">
                                                                    {log.flow_logs.map((line, lineIndex) => (
                                                                        <div key={lineIndex} className="text-main/80 flex gap-2">
                                                                            <span className="ui-line-number select-none w-6 text-right">
                                                                                {(lineIndex + 1).toString().padStart(2, "0")}
                                                                            </span>
                                                                            <span className="break-all">{line}</span>
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                            ) : (
                                                                <div className="ui-dim">
                                                                    {log.message || t("task_history_no_flow")}
                                                                </div>
                                                            )}
                                                        </>
                                                    )}
                                                    {log.flow_truncated && historyTab === "logs" && (
                                                        <div className="text-[10px] text-amber-400/90 mt-2">
                                                            {t("task_history_truncated").replace("{count}", String(log.flow_line_count || 0))}
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        </details>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
