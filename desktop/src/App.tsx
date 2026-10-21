import React from "react";
import { AppProvider, useApp } from "./context/AppContext";
import { Sidebar } from "./components/Sidebar";
import { Header } from "./components/Header";
import { ToastContainer } from "./components/Toast";
import { LicenseModal } from "./components/LicenseModal";

import { OverviewPage } from "./pages/OverviewPage";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { GroupsPage } from "./pages/GroupsPage";
import { LeaderboardPage } from "./pages/LeaderboardPage";
import { SignalsPage } from "./pages/SignalsPage";
import { TradingPage } from "./pages/TradingPage";
import { HistoryPage } from "./pages/HistoryPage";
import { StatsPage } from "./pages/StatsPage";
import { ReviewsPage } from "./pages/ReviewsPage";
import { LogsPage } from "./pages/LogsPage";
import { SettingsPage } from "./pages/SettingsPage";

const MainContent: React.FC = () => {
  const { tab } = useApp();

  return (
    <div className="app-container">
      <Sidebar />
      <div className="main-wrapper">
        <Header />
        <main className="content-body" style={{ position: "relative" }}>
          <div style={{ display: tab === "overview" ? "block" : "none" }}>
            <OverviewPage />
          </div>
          <div style={{ display: tab === "connections" ? "block" : "none" }}>
            <ConnectionsPage />
          </div>
          <div style={{ display: tab === "groups" ? "block" : "none" }}>
            <GroupsPage />
          </div>
          <div style={{ display: tab === "leaderboard" ? "block" : "none" }}>
            <LeaderboardPage />
          </div>
          <div style={{ display: tab === "signals" ? "block" : "none" }}>
            <SignalsPage />
          </div>
          <div style={{ display: tab === "trading" ? "block" : "none" }}>
            <TradingPage />
          </div>
          <div style={{ display: tab === "history" ? "block" : "none" }}>
            <HistoryPage />
          </div>
          <div style={{ display: tab === "stats" ? "block" : "none" }}>
            <StatsPage />
          </div>
          <div style={{ display: tab === "reviews" ? "block" : "none" }}>
            <ReviewsPage />
          </div>
          <div style={{ display: tab === "logs" ? "block" : "none" }}>
            <LogsPage />
          </div>
          <div style={{ display: tab === "settings" ? "block" : "none" }}>
            <SettingsPage />
          </div>
        </main>
      </div>
      <ToastContainer />
      <LicenseModal />
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <AppProvider>
      <MainContent />
    </AppProvider>
  );
};

export default App;
