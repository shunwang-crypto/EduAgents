import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./router";

/** LearningApp：可被宿主 <LearningApp userId={...}/> 挂载；当前用 BrowserRouter 路由。 */
export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
