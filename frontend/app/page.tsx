import Dashboard from "@/components/dashboard";
import replay from "@/lib/replay.json";
import type { DashboardData } from "@/lib/types";
export default function Page() {
  return <Dashboard initialData={replay as DashboardData} />;
}
