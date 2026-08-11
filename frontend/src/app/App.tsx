import { BrowserRouter } from "react-router-dom";
import { LearningApp } from "./router";
import "../styles/globals.css";

/** Standalone Development Shell：仅这里允许使用 DEV_USER_ID。 */
const DEV_USER_ID = import.meta.env.VITE_DEV_USER_ID ?? "STU-001";

export default function App() {
  return (
    <BrowserRouter>
      <LearningApp userId={DEV_USER_ID} />
    </BrowserRouter>
  );
}
