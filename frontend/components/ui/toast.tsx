"use client";

import { useEffect, useState } from "react";

interface ToastProps {
    message: string;
    type?: "success" | "error" | "info";
    duration?: number;
    onClose: () => void;
}

export function Toast({ message, type = "info", duration = 4000, onClose }: ToastProps) {
    const [isExiting, setIsExiting] = useState(false);

    useEffect(() => {
        const timer = setTimeout(() => {
            setIsExiting(true);
            setTimeout(onClose, 300);
        }, duration);

        return () => clearTimeout(timer);
    }, [duration, onClose]);

    const getIcon = () => {
        switch (type) {
            case "success":
                return (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                );
            case "error":
                return (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                );
            default:
                return (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                );
        }
    };

    const getToneStyles = () => {
        switch (type) {
            case "success":
                return {
                    color: "#047857",
                    iconBackground: "rgba(16, 185, 129, 0.16)",
                    borderColor: "rgba(16, 185, 129, 0.55)",
                };
            case "error":
                return {
                    color: "#b91c1c",
                    iconBackground: "rgba(239, 68, 68, 0.16)",
                    borderColor: "rgba(239, 68, 68, 0.6)",
                };
            default:
                return {
                    color: "#1d4ed8",
                    iconBackground: "rgba(59, 130, 246, 0.16)",
                    borderColor: "rgba(59, 130, 246, 0.55)",
                };
        }
    };

    const toneStyles = getToneStyles();

    return (
        <div
            className={`
        ${isExiting ? "toast-exit" : "toast-enter"}
        flex items-center gap-3 px-4 py-3 rounded-xl
        border bg-white dark:bg-slate-950
        shadow-xl shadow-black/20 dark:shadow-black/40
        min-w-[280px] max-w-[400px]
      `}
            style={{ borderColor: toneStyles.borderColor, color: toneStyles.color }}
        >
            <div className="p-2 rounded-lg shrink-0" style={{ backgroundColor: toneStyles.iconBackground }}>
                {getIcon()}
            </div>
            <p className="text-sm font-semibold flex-1 antialiased" style={{ color: "var(--text-main)" }}>{message}</p>
            <button
                aria-label="Close toast"
                onClick={() => {
                    setIsExiting(true);
                    setTimeout(onClose, 300);
                }}
                className="p-1 rounded-lg transition-colors hover:bg-slate-900/10 dark:hover:bg-white/10"
                style={{ color: "#64748b" }}
            >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>
    );
}

interface ToastContainerProps {
    toasts: Array<{ id: string; message: string; type: "success" | "error" | "info" }>;
    removeToast: (id: string) => void;
}

export function ToastContainer({ toasts, removeToast }: ToastContainerProps) {
    return (
        <div className="fixed bottom-6 right-6 z-[1000] flex flex-col gap-3">
            {toasts.map((toast) => (
                <Toast
                    key={toast.id}
                    message={toast.message}
                    type={toast.type}
                    onClose={() => removeToast(toast.id)}
                />
            ))}
        </div>
    );
}

// Hook for managing toasts
export function useToast() {
    const [toasts, setToasts] = useState<Array<{ id: string; message: string; type: "success" | "error" | "info" }>>([]);

    const addToast = (message: string, type: "success" | "error" | "info" = "info") => {
        const id = Date.now().toString();
        setToasts((prev) => [...prev, { id, message, type }]);
    };

    const removeToast = (id: string) => {
        setToasts((prev) => prev.filter((toast) => toast.id !== id));
    };

    return { toasts, addToast, removeToast };
}
