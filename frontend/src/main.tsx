import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { LearningApp } from "./app/router";
import "./styles/globals.css";

/** Standalone Development Shell：
 * 仅这里允许使用 DEV_USER_ID；宿主系统直接 <LearningApp userId={真实用户} />。 */
const userId = import.meta.env.VITE_DEV_USER_ID ?? "STU-001";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <LearningApp userId={userId} />
    </BrowserRouter>
  </React.StrictMode>
);
