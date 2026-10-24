import React, { useState, useEffect, useMemo } from "react";
import {
  DownloadCloud,
  Check,
  RefreshCw,
  XCircle,
  Search,
  Pin,
  Folder,
  Layers,
  CheckSquare,
  Square,
  X,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  Clock,
  Edit3,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Zap,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { wsClient } from "../services/websocket";
import { formatDateTime } from "../utils/date";
import type { TelegramDialog, TelegramFolder, TelegramChannelMessage } from "../types/api";


export const GroupsPage: React.FC = () => {
  const { addToast } = useApp();
  const [dialogs, setDialogs] = useState<TelegramDialog[]>([]);
  const [folders, setFolders] = useState<TelegramFolder[]>([]);
  const [allowedIds, setAllowedIds] = useState<number[]>([]);
  const [savedAllowedIds, setSavedAllowedIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [autoJoining, setAutoJoining] = useState(false);

  // Filter & Search states - Default strictly to the 8 MONITORED channels
  const [selectedFolderId, setSelectedFolderId] = useState<string | number>("MONITORED");
  const [searchQuery, setSearchQuery] = useState("");
  const [filterOnlyMonitored, setFilterOnlyMonitored] = useState(true);

  // Pagination states
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(50);

  // History collection state
  const [collectingChatId, setCollectingChatId] = useState<number | null>(null);
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null);
  const [joinProgress, setJoinProgress] = useState<{
    current: number;
    total: number;
    channel_name: string;
    delay_seconds: number;
    message: string;
    status: string;
  } | null>(null);

  // Channel Messages & Edit History state
  const [viewingChat, setViewingChat] = useState<{ id: number; title: string } | null>(null);
  const [chatMessages, setChatMessages] = useState<TelegramChannelMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesTotal, setMessagesTotal] = useState(0);
  const [messagesStats, setMessagesStats] = useState<{ total_signals: number; validated_signals: number; rejected_signals: number }>({
    total_signals: 0,
    validated_signals: 0,
    rejected_signals: 0,
  });
  const [messagesFilterSignalsOnly, setMessagesFilterSignalsOnly] = useState(false);
  const [messagesPage, setMessagesPage] = useState(1);
  const [expandedEdits, setExpandedEdits] = useState<{ [msgId: number]: boolean }>({});

  const fetchDialogs = async (forceRefresh: boolean = false) => {
    setLoading(true);
    try {
      const res = await api.getTelegramDialogs(forceRefresh);
      const loadedDialogs = res.dialogs || [];
      const loadedFolders = res.folders || [];
      const loadedAllowed = res.allowed_chat_ids || [];

      setDialogs(loadedDialogs);
      setFolders(loadedFolders);
      setAllowedIds(loadedAllowed);
      setSavedAllowedIds(loadedAllowed);
    } catch (err: any) {
      addToast(err?.user_message || err?.message || "Không thể tải danh sách kênh Telegram.", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDialogs();

    // Listen to progress events
    const unsub = wsClient.subscribe((event) => {
      if (event.event_type === "task_progress") {
        if (event.payload?.task === "COLLECT_HISTORY") {
          setProgress({
            current: event.payload.current,
            total: event.payload.total,
          });
        } else if (event.payload?.task === "AUTO_JOIN_ELITE") {
          setJoinProgress({
            current: event.payload.current,
            total: event.payload.total,
            channel_name: event.payload.channel_name,
            delay_seconds: event.payload.delay_seconds,
            message: event.payload.message,
            status: event.payload.status,
          });
        }
      }
    });

    return () => unsub();
  }, []);

  // Reset page when filter or search changes
  useEffect(() => {
    setCurrentPage(1);
  }, [selectedFolderId, searchQuery, filterOnlyMonitored, pageSize]);

  const toggleChat = (chatId: number) => {
    setAllowedIds((prev) =>
      prev.includes(chatId) ? prev.filter((id) => id !== chatId) : [...prev, chatId]
    );
  };

  const handleSaveAllowlist = async () => {
    setSaving(true);
    try {
      const res = await api.updateTelegramAllowlist(allowedIds);
      if (res.success) {
        setSavedAllowedIds(allowedIds);
        addToast(`Đã lưu danh sách theo dõi (${allowedIds.length} kênh).`, "success");
      }
    } catch (err: any) {
      addToast(err?.user_message || err?.message || "Lỗi lưu danh sách theo dõi.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleAutoJoinElite = async () => {
    setAutoJoining(true);
    setJoinProgress(null);
    try {
      const res = await api.autoJoinEliteChannels();
      addToast(
        res.message || `Đã tham gia thành công ${res.joined_count} kênh mới (${res.already_count} kênh đã có sẵn).`,
        res.success ? "success" : "warning"
      );
      await fetchDialogs(true);
    } catch (err: any) {
      const msg = err?.user_message || err?.message || "Lỗi khi tự động tham gia nhóm Telegram.";
      addToast(msg, "error");
    } finally {
      setAutoJoining(false);
      setJoinProgress(null);
    }
  };

  const handleCollectHistory = async (chatId: number) => {
    setCollectingChatId(chatId);
    setProgress({ current: 0, total: 1000 });
    try {
      addToast("Bắt đầu thu thập tin nhắn lịch sử...", "info");
      const res = await api.collectTelegramHistory(chatId, 7, 1000);
      const detected = res.signals_detected ?? 0;
      const validated = res.signals_validated ?? 0;
      if (detected > 0) {
        addToast(`Thu thập xong ${res.count} tin: Tìm thấy ${detected} tín hiệu (${validated} hợp lệ)!`, "success");
      } else {
        addToast(`Đã thu thập xong ${res.count} tin nhắn vào cơ sở dữ liệu.`, "success");
      }
    } catch (err: any) {
      addToast(err?.user_message || err?.message || "Lỗi thu thập lịch sử.", "error");
    } finally {
      setCollectingChatId(null);
      setProgress(null);
    }
  };

  const handleCancelCollection = async () => {
    try {
      await api.cancelTelegramCollection();
      addToast("Đã gửi yêu cầu hủy thu thập tin nhắn.", "info");
    } catch (err: any) {
      addToast("Lỗi khi hủy thu thập.", "error");
    }
  };

  const loadChatMessages = async (chatId: number, page: number = 1, onlySignals: boolean = false) => {
    setMessagesLoading(true);
    try {
      const limit = 25;
      const offset = (page - 1) * limit;
      const res = await api.getChannelMessages(chatId, limit, offset, onlySignals);
      setChatMessages(res.messages || []);
      setMessagesTotal(res.total || 0);
      setMessagesStats({
        total_signals: res.total_signals || 0,
        validated_signals: res.validated_signals || 0,
        rejected_signals: res.rejected_signals || 0,
      });
    } catch (err: any) {
      addToast(err?.user_message || err?.message || "Không thể tải tin nhắn kênh.", "error");
    } finally {
      setMessagesLoading(false);
    }
  };

  const handleOpenChatMessages = (chat: { id: number; title: string }) => {
    setViewingChat(chat);
    setMessagesPage(1);
    setMessagesFilterSignalsOnly(false);
    setExpandedEdits({});
    loadChatMessages(chat.id, 1, false);
  };

  const handleToggleSignalsFilter = (signalsOnly: boolean) => {
    if (!viewingChat) return;
    setMessagesFilterSignalsOnly(signalsOnly);
    setMessagesPage(1);
    loadChatMessages(viewingChat.id, 1, signalsOnly);
  };

  const handleChangeMessagesPage = (newPage: number) => {
    if (!viewingChat) return;
    setMessagesPage(newPage);
    loadChatMessages(viewingChat.id, newPage, messagesFilterSignalsOnly);
  };

  const toggleEditExpanded = (msgId: number) => {
    setExpandedEdits((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  // Build folder map for quick badge lookup
  const folderTitleById = useMemo(() => {
    const map = new Map<number, string>();
    folders.forEach((f) => {
      const title = f.emoticon ? `${f.emoticon} ${f.title}` : f.title;
      map.set(f.id, title);
    });
    return map;
  }, [folders]);

  // Compute counts for tab counters
  const pinnedTotalCount = useMemo(() => {
    return dialogs.filter((d) => d.pinned || (d.folder_pinned_in && d.folder_pinned_in.length > 0)).length;
  }, [dialogs]);

  const monitoredTotalCount = allowedIds.length;

  // Filter dialogs according to active tab, search, and checkboxes
  const filteredDialogs = useMemo(() => {
    let list = dialogs;

    // 1. Filter by Folder / Tab
    if (selectedFolderId === "PINNED") {
      list = list.filter((d) => d.pinned || (d.folder_pinned_in && d.folder_pinned_in.length > 0));
    } else if (selectedFolderId === "MONITORED") {
      list = list.filter((d) => allowedIds.includes(d.id));
    } else if (selectedFolderId !== "ALL") {
      const folderIdNum = Number(selectedFolderId);
      const targetFolder = folders.find((f) => f.id === folderIdNum);
      const folderChatIds = new Set(targetFolder?.chat_ids || []);
      list = list.filter((d) => (d.folder_ids && d.folder_ids.includes(folderIdNum)) || folderChatIds.has(d.id));
    }

    // 2. Filter by Search Query
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter((d) => {
        const titleMatch = d.title && d.title.toLowerCase().includes(q);
        const idMatch = String(d.id).includes(q);
        return titleMatch || idMatch;
      });
    }

    // 3. Filter by Monitored Only toggle
    if (filterOnlyMonitored) {
      list = list.filter((d) => allowedIds.includes(d.id));
    }

    // 4. Sorting: Pinned chats float to the top
    const sorted = [...list].sort((a, b) => {
      let aPinned = a.pinned;
      let bPinned = b.pinned;

      if (typeof selectedFolderId === "number") {
        aPinned = (a.folder_pinned_in && a.folder_pinned_in.includes(selectedFolderId)) || a.pinned;
        bPinned = (b.folder_pinned_in && b.folder_pinned_in.includes(selectedFolderId)) || b.pinned;
      }

      if (aPinned && !bPinned) return -1;
      if (!aPinned && bPinned) return 1;

      // Secondary: Monitored first
      const aMonitored = allowedIds.includes(a.id);
      const bMonitored = allowedIds.includes(b.id);
      if (aMonitored && !bMonitored) return -1;
      if (!aMonitored && bMonitored) return 1;

      return (a.title || "").localeCompare(b.title || "");
    });

    return sorted;
  }, [dialogs, selectedFolderId, folders, searchQuery, filterOnlyMonitored, allowedIds]);

  // Bulk actions on currently filtered list
  const handleSelectAllFiltered = () => {
    const idsToAdd = filteredDialogs.map((d) => d.id);
    setAllowedIds((prev) => {
      const s = new Set([...prev, ...idsToAdd]);
      return Array.from(s);
    });
    addToast(`Đã chọn thêm ${idsToAdd.length} kênh trong danh sách lọc.`, "info");
  };

  const handleDeselectAllFiltered = () => {
    const idsToRemove = new Set(filteredDialogs.map((d) => d.id));
    setAllowedIds((prev) => prev.filter((id) => !idsToRemove.has(id)));
    addToast(`Đã bỏ chọn ${idsToRemove.size} kênh trong danh sách lọc.`, "info");
  };

  // Pagination calculation
  const totalFiltered = filteredDialogs.length;
  const isAllPages = pageSize >= 10000;
  const totalPages = isAllPages ? 1 : Math.max(1, Math.ceil(totalFiltered / pageSize));
  const validCurrentPage = Math.min(currentPage, totalPages);

  const paginatedDialogs = useMemo(() => {
    if (isAllPages) return filteredDialogs;
    const start = (validCurrentPage - 1) * pageSize;
    return filteredDialogs.slice(start, start + pageSize);
  }, [filteredDialogs, validCurrentPage, pageSize, isAllPages]);

  // Detect unsaved changes
  const hasUnsavedChanges = useMemo(() => {
    if (allowedIds.length !== savedAllowedIds.length) return true;
    const savedSet = new Set(savedAllowedIds);
    return allowedIds.some((id) => !savedSet.has(id));
  }, [allowedIds, savedAllowedIds]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {/* 1. Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px" }}>
        <div>
          <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Nhóm & Kênh Tín Hiệu Telegram</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
            Trích xuất trực tiếp Thư mục (Chat Folders), nhóm được ghim (Pinned) và danh sách kênh để bot theo dõi tín hiệu.
          </p>
        </div>
        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <button
            className="btn btn-secondary"
            onClick={handleAutoJoinElite}
            disabled={autoJoining}
            title="Tự động tham gia 8 kênh tín hiệu tinh hoa và đưa vào danh sách theo dõi"
            style={{
              borderColor: "rgba(16, 185, 129, 0.4)",
              color: "#34d399",
              background: "rgba(16, 185, 129, 0.1)",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            {autoJoining ? <RefreshCw size={14} className="spin" /> : <Zap size={14} />}
            <span>{autoJoining ? "Đang tham gia..." : "⚡ Auto-Join 8 Kênh Tinh Hoa"}</span>
          </button>
          <button className="btn btn-secondary" onClick={() => fetchDialogs(true)} disabled={loading} title="Tải lại từ Telegram">
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            <span>Tải lại</span>
          </button>
          <button
            className={`btn ${hasUnsavedChanges ? "btn-primary" : "btn-secondary"}`}
            onClick={handleSaveAllowlist}
            disabled={saving}
            style={{
              backgroundColor: hasUnsavedChanges ? "var(--color-accent)" : undefined,
              boxShadow: hasUnsavedChanges ? "0 0 10px rgba(59, 130, 246, 0.5)" : undefined,
            }}
          >
            <Check size={14} />
            <span>{saving ? "Đang lưu..." : hasUnsavedChanges ? `Lưu thay đổi (${allowedIds.length})` : "Đã lưu danh sách"}</span>
          </button>
        </div>
      </div>

      {/* Auto-Join Progress Bar Banner */}
      {autoJoining && (
        <div
          style={{
            padding: "12px 16px",
            background: "rgba(5, 150, 105, 0.12)",
            border: "1px solid rgba(16, 185, 129, 0.35)",
            borderRadius: "8px",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "13px" }}>
            <span style={{ fontWeight: 600, color: "#34d399", display: "flex", alignItems: "center", gap: "8px" }}>
              <RefreshCw size={14} className="spin" />
              {joinProgress?.message || "Đang kết nối và chuẩn bị tham gia nhóm..."}
            </span>
            <span style={{ fontWeight: 700, color: "#fff", fontSize: "12px" }}>
              {joinProgress ? `${joinProgress.current}/${joinProgress.total}` : "1/5"}
            </span>
          </div>

          <div
            style={{
              width: "100%",
              height: "6px",
              background: "rgba(255, 255, 255, 0.1)",
              borderRadius: "3px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${joinProgress ? Math.min(100, Math.max(10, (joinProgress.current / joinProgress.total) * 100)) : 15}%`,
                background: "linear-gradient(90deg, #10b981 0%, #34d399 100%)",
                borderRadius: "3px",
                transition: "width 0.4s ease-in-out",
              }}
            />
          </div>
        </div>
      )}

      {/* Unsaved changes notification banner */}
      {hasUnsavedChanges && (
        <div
          style={{
            background: "rgba(245, 158, 11, 0.12)",
            border: "1px solid rgba(245, 158, 11, 0.4)",
            borderRadius: "8px",
            padding: "10px 16px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px", color: "var(--color-warning)" }}>
            <span style={{ fontSize: "16px" }}>⚠️</span>
            <span style={{ fontSize: "13px", fontWeight: 500 }}>
              Bạn có thay đổi chưa lưu vào danh sách theo dõi ({allowedIds.length} kênh được chọn).
            </span>
          </div>
          <button className="btn btn-primary btn-sm" onClick={handleSaveAllowlist} disabled={saving}>
            Lưu ngay
          </button>
        </div>
      )}

      {/* History collection progress */}
      {progress && (
        <div className="card" style={{ border: "1px solid var(--color-accent)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
            <span style={{ fontWeight: 600, color: "#fff" }}>
              Đang thu thập lịch sử tin nhắn ({progress.current} / {progress.total})
            </span>
            <button className="btn btn-danger btn-sm" onClick={handleCancelCollection}>
              <XCircle size={14} />
              <span>Dừng lại</span>
            </button>
          </div>
          <div style={{ background: "var(--bg-input)", height: "8px", borderRadius: "4px", overflow: "hidden" }}>
            <div
              style={{
                width: `${Math.min(100, (progress.current / progress.total) * 100)}%`,
                height: "100%",
                backgroundColor: "var(--color-accent)",
                transition: "width 0.3s ease",
              }}
            />
          </div>
        </div>
      )}

      {/* 2. Telegram Folders Tab Bar (Telegram Desktop Style) */}
      <div
        style={{
          display: "flex",
          gap: "8px",
          overflowX: "auto",
          paddingBottom: "4px",
          borderBottom: "1px solid var(--border-color)",
        }}
      >
        {/* Tab Đang theo dõi (Kênh yêu cầu) */}
        <button
          onClick={() => setSelectedFolderId("MONITORED")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "8px 14px",
            borderRadius: "8px 8px 0 0",
            border: "none",
            borderBottom: selectedFolderId === "MONITORED" ? "2px solid var(--color-success)" : "2px solid transparent",
            background: selectedFolderId === "MONITORED" ? "var(--color-success-bg)" : "transparent",
            color: selectedFolderId === "MONITORED" ? "#6ee7b7" : "var(--text-secondary)",
            fontWeight: selectedFolderId === "MONITORED" ? 600 : 500,
            cursor: "pointer",
            whiteSpace: "nowrap",
            transition: "all 0.2s ease",
          }}
        >
          <Check size={14} style={{ color: "var(--color-success)" }} />
          <span>Đang theo dõi ({monitoredTotalCount} kênh)</span>
          <span
            style={{
              fontSize: "11px",
              padding: "2px 6px",
              borderRadius: "10px",
              background: selectedFolderId === "MONITORED" ? "var(--color-success)" : "var(--bg-input)",
              color: "#fff",
            }}
          >
            {monitoredTotalCount}
          </span>
        </button>

        {/* Tab Đã ghim */}
        <button
          onClick={() => setSelectedFolderId("PINNED")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "8px 14px",
            borderRadius: "8px 8px 0 0",
            border: "none",
            borderBottom: selectedFolderId === "PINNED" ? "2px solid #eab308" : "2px solid transparent",
            background: selectedFolderId === "PINNED" ? "rgba(234, 179, 8, 0.12)" : "transparent",
            color: selectedFolderId === "PINNED" ? "#fef08a" : "var(--text-secondary)",
            fontWeight: selectedFolderId === "PINNED" ? 600 : 500,
            cursor: "pointer",
            whiteSpace: "nowrap",
            transition: "all 0.2s ease",
          }}
        >
          <Pin size={14} style={{ color: "#eab308" }} />
          <span>Đã ghim</span>
          <span
            style={{
              fontSize: "11px",
              padding: "2px 6px",
              borderRadius: "10px",
              background: selectedFolderId === "PINNED" ? "#ca8a04" : "var(--bg-input)",
              color: "#fff",
            }}
          >
            {pinnedTotalCount}
          </span>
        </button>

        {/* Tab Tất cả */}
        <button
          onClick={() => setSelectedFolderId("ALL")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "8px 14px",
            borderRadius: "8px 8px 0 0",
            border: "none",
            borderBottom: selectedFolderId === "ALL" ? "2px solid var(--color-accent)" : "2px solid transparent",
            background: selectedFolderId === "ALL" ? "rgba(59, 130, 246, 0.12)" : "transparent",
            color: selectedFolderId === "ALL" ? "#fff" : "var(--text-secondary)",
            fontWeight: selectedFolderId === "ALL" ? 600 : 500,
            cursor: "pointer",
            whiteSpace: "nowrap",
            transition: "all 0.2s ease",
          }}
        >
          <Layers size={14} />
          <span>Tất cả</span>
          <span
            style={{
              fontSize: "11px",
              padding: "2px 6px",
              borderRadius: "10px",
              background: selectedFolderId === "ALL" ? "var(--color-accent)" : "var(--bg-input)",
              color: "#fff",
            }}
          >
            {dialogs.length}
          </span>
        </button>

        {/* Dynamic Telegram Chat Folders */}
        {folders.map((f) => {
          const isActive = selectedFolderId === f.id;
          return (
            <button
              key={f.id}
              onClick={() => setSelectedFolderId(f.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "8px 14px",
                borderRadius: "8px 8px 0 0",
                border: "none",
                borderBottom: isActive ? "2px solid var(--color-accent)" : "2px solid transparent",
                background: isActive ? "rgba(59, 130, 246, 0.12)" : "transparent",
                color: isActive ? "#fff" : "var(--text-secondary)",
                fontWeight: isActive ? 600 : 500,
                cursor: "pointer",
                whiteSpace: "nowrap",
                transition: "all 0.2s ease",
              }}
            >
              {f.emoticon ? (
                <span style={{ fontSize: "14px" }}>{f.emoticon}</span>
              ) : (
                <Folder size={14} style={{ color: isActive ? "var(--color-accent)" : "var(--text-muted)" }} />
              )}
              <span>{f.title}</span>
              <span
                style={{
                  fontSize: "11px",
                  padding: "2px 6px",
                  borderRadius: "10px",
                  background: isActive ? "var(--color-accent)" : "var(--bg-input)",
                  color: "#fff",
                }}
              >
                {f.chat_count}
              </span>
            </button>
          );
        })}
      </div>

      {/* 3. Search and Action Toolbar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          background: "var(--bg-card)",
          padding: "12px 16px",
          borderRadius: "8px",
          border: "1px solid var(--border-color)",
        }}
      >
        {/* Search Input */}
        <div style={{ position: "relative", minWidth: "280px", flex: "1 1 320px", maxWidth: "500px" }}>
          <Search
            size={16}
            style={{
              position: "absolute",
              left: "12px",
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--text-muted)",
              pointerEvents: "none",
            }}
          />
          <input
            type="text"
            className="input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Tìm theo tên nhóm, kênh hoặc Chat ID..."
            style={{
              paddingLeft: "36px",
              paddingRight: searchQuery ? "32px" : "12px",
              width: "100%",
              height: "36px",
              fontSize: "13px",
            }}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              style={{
                position: "absolute",
                right: "10px",
                top: "50%",
                transform: "translateY(-50%)",
                background: "transparent",
                border: "none",
                color: "var(--text-muted)",
                cursor: "pointer",
                padding: "2px",
                display: "flex",
                alignItems: "center",
              }}
              title="Xóa tìm kiếm"
            >
              <X size={14} />
            </button>
          )}
        </div>

        {/* Quick Batch Actions & Filter Toggles */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleSelectAllFiltered}
            title="Thêm tất cả các kênh đang hiển thị vào danh sách theo dõi"
          >
            <CheckSquare size={13} />
            <span>Chọn tất cả ({totalFiltered})</span>
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleDeselectAllFiltered}
            title="Bỏ chọn tất cả các kênh đang hiển thị"
          >
            <Square size={13} />
            <span>Bỏ chọn</span>
          </button>

          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              fontSize: "12px",
              color: "var(--text-secondary)",
              cursor: "pointer",
              userSelect: "none",
              paddingLeft: "6px",
            }}
          >
            <input
              type="checkbox"
              checked={filterOnlyMonitored}
              onChange={(e) => setFilterOnlyMonitored(e.target.checked)}
              style={{ cursor: "pointer", width: "14px", height: "14px" }}
            />
            <span>Chỉ hiện đã chọn</span>
          </label>

          {/* Page Size Selector */}
          <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--text-muted)" }}>
            <span>Hiện:</span>
            <select
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              className="input"
              style={{ height: "30px", padding: "2px 8px", fontSize: "12px", width: "80px" }}
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={10000}>Tất cả</option>
            </select>
          </div>
        </div>
      </div>

      {/* 4. Chats Table Container */}
      <div className="table-container" style={{ margin: 0 }}>
        <div className="table-header">
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span className="table-title">
              Danh sách Hội thoại{" "}
              <span style={{ fontSize: "12px", color: "var(--text-muted)", fontWeight: "normal" }}>
                (Hiển thị {paginatedDialogs.length} / {totalFiltered} kết quả)
              </span>
            </span>
          </div>
          <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>
            Đang theo dõi: <strong style={{ color: "var(--color-success)" }}>{allowedIds.length}</strong> / {dialogs.length} kênh
          </span>
        </div>

        <table>
          <thead>
            <tr>
              <th style={{ width: "50px", textAlign: "center" }}>Theo dõi</th>
              <th>Tên Nhóm / Kênh Telegram</th>
              <th style={{ width: "130px" }}>Loại</th>
              <th style={{ width: "140px" }}>Chat ID</th>
              <th style={{ width: "90px", textAlign: "center" }}>Chưa đọc</th>
              <th style={{ width: "160px", textAlign: "right" }}>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {paginatedDialogs.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", color: "var(--text-muted)", padding: "40px" }}>
                  {loading
                    ? "Đang tải danh sách hội thoại từ Telegram..."
                    : searchQuery
                    ? `Không tìm thấy nhóm/kênh nào khớp với từ khóa "${searchQuery}".`
                    : "Không có hội thoại nào trong thư mục này."}
                </td>
              </tr>
            ) : (
              paginatedDialogs.map((d) => {
                const isMonitored = allowedIds.includes(d.id);
                const isCollecting = collectingChatId === d.id;

                // Check pinned status
                const isPinnedInCurrentView =
                  typeof selectedFolderId === "number"
                    ? (d.folder_pinned_in && d.folder_pinned_in.includes(selectedFolderId)) || d.pinned
                    : d.pinned;

                return (
                  <tr
                    key={d.id}
                    style={{
                      backgroundColor: isMonitored ? "rgba(59, 130, 246, 0.04)" : undefined,
                    }}
                  >
                    {/* Checkbox */}
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={isMonitored}
                        onChange={() => toggleChat(d.id)}
                        style={{ cursor: "pointer", width: "16px", height: "16px" }}
                      />
                    </td>

                    {/* Chat Title & Badges */}
                    <td>
                      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          {isPinnedInCurrentView && (
                            <span
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: "3px",
                                background: "rgba(234, 179, 8, 0.15)",
                                color: "#facc15",
                                border: "1px solid rgba(234, 179, 8, 0.3)",
                                borderRadius: "4px",
                                padding: "1px 5px",
                                fontSize: "10px",
                                fontWeight: 700,
                              }}
                              title="Hội thoại được ghim trong Telegram"
                            >
                              <Pin size={10} />
                              Ghim
                            </span>
                          )}
                          <span
                            style={{ fontWeight: 600, color: "#fff", fontSize: "13px", cursor: "pointer" }}
                            onClick={() => handleOpenChatMessages({ id: d.id, title: d.title })}
                            title="Bấm để xem tin nhắn đồng bộ và lịch sử sửa đổi từ Telegram"
                          >
                            {d.title}
                          </span>
                        </div>

                        {/* Associated Folders Pills */}
                        {d.folder_ids && d.folder_ids.length > 0 && (
                          <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                            {d.folder_ids.map((fid) => {
                              const ftitle = folderTitleById.get(fid) || `Folder #${fid}`;
                              return (
                                <span
                                  key={fid}
                                  style={{
                                    fontSize: "10px",
                                    padding: "1px 6px",
                                    borderRadius: "4px",
                                    background: "rgba(255, 255, 255, 0.06)",
                                    color: "var(--text-muted)",
                                    border: "1px solid var(--border-color)",
                                  }}
                                >
                                  {ftitle}
                                </span>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </td>

                    {/* Type */}
                    <td>
                      <span className="badge badge-live-off">
                        {d.is_channel ? "Kênh Broadcast" : d.is_group ? "Nhóm Supergroup" : "Hội thoại"}
                      </span>
                    </td>

                    {/* Chat ID */}
                    <td className="mono" style={{ color: "var(--text-secondary)", fontSize: "12px" }}>
                      {d.id}
                    </td>

                    {/* Unread */}
                    <td style={{ textAlign: "center" }}>
                      {d.unread_count > 0 ? (
                        <span
                          style={{
                            display: "inline-block",
                            padding: "2px 8px",
                            borderRadius: "10px",
                            background: "rgba(59, 130, 246, 0.15)",
                            color: "var(--color-accent)",
                            fontSize: "11px",
                            fontWeight: 600,
                          }}
                        >
                          +{d.unread_count}
                        </span>
                      ) : (
                        <span style={{ color: "var(--text-muted)", fontSize: "11px" }}>0</span>
                      )}
                    </td>

                    {/* Action buttons */}
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <div style={{ display: "flex", gap: "6px", justifyContent: "flex-end" }}>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleOpenChatMessages({ id: d.id, title: d.title })}
                          title="Xem tin nhắn đồng bộ và lịch sử sửa đổi từ Telegram"
                          style={{ display: "flex", alignItems: "center", gap: "4px" }}
                        >
                          <MessageSquare size={13} />
                          <span>Xem tin</span>
                        </button>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleCollectHistory(d.id)}
                          disabled={isCollecting}
                          title="Thu thập 7 ngày tin nhắn gần nhất để phân tích tín hiệu"
                        >
                          <DownloadCloud size={13} />
                          <span>{isCollecting ? "Đang quét..." : "Quét 7d"}</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>

        {/* 5. Pagination Footer */}
        {totalPages > 1 && (
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "12px 18px",
              borderTop: "1px solid var(--border-color)",
              background: "var(--bg-card)",
              flexWrap: "wrap",
              gap: "10px",
            }}
          >
            <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>
              Trang {validCurrentPage} / {totalPages} (Hiển thị {(validCurrentPage - 1) * pageSize + 1} -{" "}
              {Math.min(validCurrentPage * pageSize, totalFiltered)} trong {totalFiltered} kênh)
            </span>

            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={validCurrentPage <= 1}
              >
                <ChevronLeft size={14} />
                <span>Trước</span>
              </button>

              {/* Page numbers (up to 5 pages shown) */}
              {Array.from({ length: Math.min(5, totalPages) }, (_, idx) => {
                let pageNum = validCurrentPage - 2 + idx;
                if (pageNum < 1) pageNum = idx + 1;
                if (pageNum > totalPages) pageNum = totalPages - (4 - idx);
                if (pageNum < 1 || pageNum > totalPages) return null;

                const isCurrent = pageNum === validCurrentPage;
                return (
                  <button
                    key={pageNum}
                    onClick={() => setCurrentPage(pageNum)}
                    className="btn btn-sm"
                    style={{
                      background: isCurrent ? "var(--color-accent)" : "transparent",
                      color: isCurrent ? "#fff" : "var(--text-secondary)",
                      border: isCurrent ? "1px solid var(--color-accent)" : "1px solid var(--border-color)",
                      minWidth: "30px",
                      padding: "4px 8px",
                    }}
                  >
                    {pageNum}
                  </button>
                );
              })}

              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={validCurrentPage >= totalPages}
              >
                <span>Sau</span>
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 6. Channel Messages & Edit History Modal */}
      {viewingChat && (
        <div className="modal-overlay" onClick={() => setViewingChat(null)}>
          <div
            className="modal-content"
            style={{ maxWidth: "850px", maxHeight: "90vh", display: "flex", flexDirection: "column" }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="modal-header" style={{ padding: "16px 20px", borderBottom: "1px solid var(--border-color)" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <MessageSquare size={18} className="text-accent" />
                  <h3 style={{ margin: 0, fontSize: "16px", color: "#fff" }}>
                    Tin nhắn đồng bộ Telegram: {viewingChat.title}
                  </h3>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>
                  Chat ID: <span className="mono">{viewingChat.id}</span> • Tổng số tin: <strong style={{ color: "#fff" }}>{messagesTotal}</strong> • Tín hiệu: <strong style={{ color: "var(--color-accent)" }}>{messagesStats.total_signals}</strong> (<span style={{ color: "var(--color-success)" }}>{messagesStats.validated_signals} Hợp lệ</span>, <span style={{ color: "var(--color-danger)" }}>{messagesStats.rejected_signals} Bị từ chối</span>)
                </div>
              </div>
              <button
                onClick={() => setViewingChat(null)}
                style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "18px" }}
              >
                ✕
              </button>
            </div>

            {/* Filter Toolbar */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "10px 20px",
                background: "rgba(255,255,255,0.02)",
                borderBottom: "1px solid var(--border-color)",
                gap: "10px",
                flexWrap: "wrap",
              }}
            >
              <div style={{ display: "flex", gap: "6px" }}>
                <button
                  className={`btn btn-sm ${!messagesFilterSignalsOnly ? "btn-primary" : "btn-secondary"}`}
                  onClick={() => handleToggleSignalsFilter(false)}
                >
                  Tất cả tin nhắn ({messagesTotal})
                </button>
                <button
                  className={`btn btn-sm ${messagesFilterSignalsOnly ? "btn-primary" : "btn-secondary"}`}
                  onClick={() => handleToggleSignalsFilter(true)}
                >
                  Chỉ tin chứa tín hiệu ({messagesStats.total_signals})
                </button>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => loadChatMessages(viewingChat.id, messagesPage, messagesFilterSignalsOnly)}
                  disabled={messagesLoading}
                  title="Làm mới danh sách tin nhắn"
                >
                  <RefreshCw size={12} className={messagesLoading ? "spin" : ""} />
                  <span>Làm mới</span>
                </button>
              </div>
            </div>

            {/* Modal Body: Message List */}
            <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: "12px" }}>
              {messagesLoading ? (
                <div style={{ textAlign: "center", padding: "40px", color: "var(--text-muted)" }}>
                  <RefreshCw size={24} className="spin" style={{ margin: "0 auto 12px" }} />
                  <div>Đang tải tin nhắn đồng bộ từ Telegram...</div>
                </div>
              ) : chatMessages.length === 0 ? (
                <div style={{ textAlign: "center", padding: "40px", color: "var(--text-muted)", background: "var(--bg-input)", borderRadius: "8px" }}>
                  <MessageSquare size={32} style={{ opacity: 0.3, margin: "0 auto 12px" }} />
                  <div>Không tìm thấy tin nhắn nào trong cơ sở dữ liệu.</div>
                  <div style={{ fontSize: "12px", marginTop: "6px" }}>
                    Bấm nút <strong>"Quét 7d"</strong> bên ngoài danh sách để cào tin nhắn từ kênh này về máy.
                  </div>
                </div>
              ) : (
                chatMessages.map((msg) => {
                  const hasSignal = Boolean(msg.signal_id);
                  const isLong = msg.side === "LONG" || msg.side === "BUY";
                  const hasEdits = msg.has_edits || (msg.versions && msg.versions.length > 1);
                  const isExpanded = Boolean(expandedEdits[msg.message_id]);

                  return (
                    <div
                      key={msg.message_id}
                      style={{
                        background: hasSignal ? "rgba(59, 130, 246, 0.04)" : "rgba(255,255,255,0.02)",
                        border: hasSignal ? "1px solid rgba(59, 130, 246, 0.3)" : "1px solid var(--border-color)",
                        borderRadius: "8px",
                        padding: "12px 14px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "8px",
                      }}
                    >
                      {/* Message Meta Header */}
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span
                            className="mono"
                            style={{
                              fontSize: "11px",
                              color: "var(--text-muted)",
                              background: "rgba(255,255,255,0.06)",
                              padding: "2px 6px",
                              borderRadius: "4px",
                            }}
                          >
                            #{msg.message_id}
                          </span>
                          <span style={{ fontSize: "12px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "4px" }}>
                            <Clock size={12} />
                            {msg.telegram_timestamp ? formatDateTime(msg.telegram_timestamp) : "—"}
                          </span>
                        </div>

                        {/* Edit History Badge / Toggle */}
                        {hasEdits && (
                          <button
                            onClick={() => toggleEditExpanded(msg.message_id)}
                            style={{
                              background: "rgba(245, 158, 11, 0.15)",
                              border: "1px solid rgba(245, 158, 11, 0.3)",
                              color: "#f59e0b",
                              borderRadius: "4px",
                              padding: "2px 8px",
                              fontSize: "11px",
                              fontWeight: 600,
                              cursor: "pointer",
                              display: "flex",
                              alignItems: "center",
                              gap: "4px",
                            }}
                            title="Bấm để xem lịch sử chỉnh sửa tin nhắn này"
                          >
                            <Edit3 size={11} />
                            <span>Đã chỉnh sửa ({msg.versions?.length || 2} bản)</span>
                            {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                          </button>
                        )}
                      </div>

                      {/* Expanded Edit Versions View */}
                      {hasEdits && isExpanded && msg.versions && msg.versions.length > 0 && (
                        <div style={{ background: "var(--bg-input)", border: "1px solid rgba(245, 158, 11, 0.3)", borderRadius: "6px", padding: "10px", margin: "4px 0" }}>
                          <div style={{ fontSize: "11px", fontWeight: 700, color: "#f59e0b", marginBottom: "8px" }}>
                            Lịch sử chỉnh sửa tin nhắn từ Telegram:
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                            {msg.versions.map((v) => (
                              <div key={v.version} style={{ borderBottom: "1px dashed var(--border-color)", paddingBottom: "6px" }}>
                                <div style={{ fontSize: "11px", color: "var(--text-muted)", display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                                  <span style={{ fontWeight: 600, color: v.is_edit ? "#f59e0b" : "#10b981" }}>
                                    Phiên bản {v.version} {v.is_edit ? "(Chỉnh sửa)" : "(Bản gốc ban đầu)"}
                                  </span>
                                  <span>{formatDateTime(v.event_date || v.received_at)}</span>
                                </div>
                                <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: "12px", fontFamily: "var(--font-mono)", color: "#e2e8f0" }}>
                                  {v.raw_text}
                                </pre>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Raw Telegram Message Text */}
                      {(!hasEdits || !isExpanded) && (
                        <pre
                          style={{
                            margin: 0,
                            whiteSpace: "pre-wrap",
                            fontSize: "12px",
                            fontFamily: "var(--font-mono)",
                            background: "var(--bg-input)",
                            padding: "10px",
                            borderRadius: "6px",
                            border: "1px solid var(--border-color)",
                            maxHeight: "160px",
                            overflowY: "auto",
                            color: "#e2e8f0",
                          }}
                        >
                          {msg.raw_text}
                        </pre>
                      )}

                      {/* Bot Scan Result Card */}
                      {hasSignal ? (
                        <div
                          style={{
                            background: "rgba(0,0,0,0.25)",
                            border: "1px solid var(--border-color)",
                            borderRadius: "6px",
                            padding: "8px 12px",
                            display: "flex",
                            flexDirection: "column",
                            gap: "6px",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                              <span
                                className="badge"
                                style={
                                  isLong
                                    ? { background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)", fontWeight: 700 }
                                    : { background: "rgba(239, 68, 68, 0.15)", color: "#ef4444", border: "1px solid rgba(239, 68, 68, 0.3)", fontWeight: 700 }
                                }
                              >
                                {isLong ? "LONG" : "SHORT"} {msg.leverage ? `${msg.leverage}x` : ""}
                              </span>
                              <strong className="mono" style={{ color: "#fff", fontSize: "13px" }}>
                                {msg.symbol}
                              </strong>
                              <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                                Entry: <span className="mono" style={{ color: "#fff" }}>{msg.entries && msg.entries.length > 0 ? msg.entries.join(" - ") : "Market"}</span>
                              </span>
                              <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                                SL: <span className="mono text-danger" style={{ fontWeight: 600 }}>{msg.stop_loss || "—"}</span>
                              </span>
                              <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                                TP: <span className="mono text-success">{msg.take_profits && msg.take_profits.length > 0 ? msg.take_profits.join(", ") : "—"}</span>
                              </span>
                            </div>

                            <div>
                              {(() => {
                                switch (msg.state) {
                                  case "VALIDATED":
                                    return <span className="badge badge-read-only" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)" }}>HỢP LỆ (VALIDATED)</span>;
                                  case "ENTRY_PENDING":
                                  case "PENDING_ENTRY":
                                    return <span className="badge badge-shadow" style={{ color: "#3b82f6" }}>CHỜ KHỚP LỆNH</span>;
                                  case "REJECTED":
                                    return <span className="badge badge-live-off" style={{ opacity: 0.8, color: "#fca5a5" }}>BỊ TỪ CHỐI</span>;
                                  case "NEEDS_REVIEW":
                                  case "NEEDS_POLICY":
                                    return <span className="badge badge-live" style={{ background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b" }}>CẦN XEM XÉT</span>;
                                  default:
                                    return <span className="badge">{msg.state}</span>;
                                }
                              })()}
                            </div>
                          </div>

                          {msg.blocking_reason && (
                            <div
                              style={{
                                fontSize: "11px",
                                color: msg.state === "CLOSED" ? "#86efac" : "#fca5a5",
                                display: "flex",
                                alignItems: "center",
                                gap: "4px",
                              }}
                            >
                              {msg.state === "CLOSED" ? (
                                <Check size={12} style={{ flexShrink: 0 }} />
                              ) : (
                                <AlertTriangle size={12} style={{ flexShrink: 0 }} />
                              )}
                              <span>
                                {msg.state === "CLOSED"
                                  ? "Trạng thái đóng lệnh:"
                                  : "Lý do bot từ chối / chặn:"}{" "}
                                <strong>{msg.blocking_reason}</strong>
                              </span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div style={{ fontSize: "11px", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: "4px" }}>
                          <span>💬 Tin nhắn chat / không chứa cú pháp vào lệnh</span>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {/* Modal Footer with Pagination */}
            <div
              className="modal-footer"
              style={{
                padding: "12px 20px",
                borderTop: "1px solid var(--border-color)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                Trang {messagesPage} / {Math.max(1, Math.ceil(messagesTotal / 25))} (Tổng {messagesTotal} tin)
              </div>

              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => handleChangeMessagesPage(Math.max(1, messagesPage - 1))}
                  disabled={messagesPage <= 1 || messagesLoading}
                >
                  <ChevronLeft size={13} />
                  <span>Trang trước</span>
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => handleChangeMessagesPage(messagesPage + 1)}
                  disabled={chatMessages.length < 25 || messagesPage * 25 >= messagesTotal || messagesLoading}
                >
                  <span>Trang sau</span>
                  <ChevronRight size={13} />
                </button>
                <button className="btn btn-secondary btn-sm" onClick={() => setViewingChat(null)}>
                  Đóng
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
