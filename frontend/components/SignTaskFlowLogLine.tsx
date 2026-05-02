type ParsedActionFlowLog = {
    prefix: string;
    chatId?: string;
    name?: string;
    deleteAfter?: string;
    actions: string[];
    details: string[];
};

const normalizeBoxLine = (line: string) => (
    line
        .replace(/[╔╗╚╝╟╢║═─]/g, "")
        .trim()
);

const parseActionFlowLog = (line: string): ParsedActionFlowLog | null => {
    if (!line.includes("╔") || !line.includes("Actions Flow")) {
        return null;
    }

    const lines = line.split(/\r?\n/);
    const prefix = lines[0]?.trim() || "";
    const fields: ParsedActionFlowLog = { prefix, actions: [], details: [] };

    for (const rawLine of lines.slice(1)) {
        const text = normalizeBoxLine(rawLine);
        if (!text) continue;

        const [rawKey, ...rawValueParts] = text.split(":");
        const key = rawKey.trim();
        const value = rawValueParts.join(":").trim();

        if (key === "Chat ID") {
            fields.chatId = value;
            continue;
        }
        if (key === "Name") {
            fields.name = value;
            continue;
        }
        if (key === "Delete After") {
            fields.deleteAfter = value || "-";
            continue;
        }
        if (key === "Actions Flow") {
            continue;
        }

        if (/^\d+\./.test(text)) {
            fields.actions.push(text);
            continue;
        }

        fields.details.push(text);
    }

    if (!fields.chatId && !fields.name && fields.actions.length === 0) {
        return null;
    }

    return fields;
};

export function SignTaskFlowLogLine({ line, t }: { line: string; t: (key: string) => string }) {
    const parsed = parseActionFlowLog(line);

    if (!parsed) {
        return <span className="block overflow-x-auto whitespace-pre py-0.5">{line}</span>;
    }

    return (
        <span className="block min-w-0 space-y-2">
            {parsed.prefix && <span className="block whitespace-pre-wrap break-words">{parsed.prefix}</span>}
            <span className="block rounded-lg border border-[#8a3ffc]/20 bg-[#8a3ffc]/5 p-3 text-[11px] leading-relaxed">
                <span className="grid gap-1 sm:grid-cols-3">
                    <span className="rounded-md bg-white/5 px-2 py-1">
                        <span className="ui-muted mr-1">Chat ID</span>
                        <span className="font-mono">{parsed.chatId || "-"}</span>
                    </span>
                    <span className="rounded-md bg-white/5 px-2 py-1">
                        <span className="ui-muted mr-1">{t("task_flow_name")}</span>
                        <span>{parsed.name || "-"}</span>
                    </span>
                    <span className="rounded-md bg-white/5 px-2 py-1">
                        <span className="ui-muted mr-1">{t("task_flow_delete_after")}</span>
                        <span>{parsed.deleteAfter || "-"}</span>
                    </span>
                </span>
                {parsed.details.length > 0 && (
                    <span className="mt-3 block space-y-1">
                        {parsed.details.map((detail, index) => (
                            <span key={`${detail}-${index}`} className="block rounded-md border border-white/8 bg-white/5 px-2 py-1 whitespace-pre-wrap break-words">
                                {detail}
                            </span>
                        ))}
                    </span>
                )}
                {parsed.actions.length > 0 && (
                    <span className="mt-3 block space-y-1">
                        <span className="block text-[10px] font-bold uppercase tracking-wider ui-muted">{t("task_flow_actions")}</span>
                        {parsed.actions.map((action, index) => (
                            <span key={`${action}-${index}`} className="block rounded-md border border-white/8 bg-white/5 px-2 py-1 break-words">
                                {action}
                            </span>
                        ))}
                    </span>
                )}
            </span>
        </span>
    );
}
