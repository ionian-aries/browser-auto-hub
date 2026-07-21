import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MainLayout } from "./layouts/MainLayout";
import { Dashboard } from "./pages/Dashboard";
import { Pipelines } from "./pages/Pipelines";
import { PipelineDetail } from "./pages/PipelineDetail";
import { Executions } from "./pages/Executions";
import { ExecutionDetail } from "./pages/ExecutionDetail";
import { Settings } from "./pages/Settings";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/pipelines" element={<Pipelines />} />
            <Route path="/pipelines/:name" element={<PipelineDetail />} />
            <Route path="/executions" element={<Executions />} />
            <Route path="/executions/:id" element={<ExecutionDetail />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
