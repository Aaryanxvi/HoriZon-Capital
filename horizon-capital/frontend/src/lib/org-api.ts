import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";

// Static org chart — backend/app/api/desktop_org.py. Answers with the engine off.
export interface OrgDepartment {
  id: string;
  label: string;
}

export interface OrgAgent {
  id: string;
  label: string;
  department: string;
  role: string;
  subscribes: string[];
  emits: string[];
  enabled: boolean;
  note: string | null;
}

export interface OrgLink {
  from: string;
  to: string;
  channels: string[]; // emitted channel globs, e.g. "horizon.signal.*"
}

export interface OrgResponse {
  departments: OrgDepartment[];
  agents: OrgAgent[];
  links: OrgLink[];
}

export const useOrg = () =>
  useQuery({
    queryKey: ["org"],
    queryFn: async () => {
      const res = await fetch("/api/desktop/org");
      if (!res.ok) throw new ApiError(`/org failed (${res.status})`, res.status);
      return (await res.json()) as OrgResponse;
    },
    staleTime: Infinity,
  });

/** Bus glob match ("*" spans dots, as fnmatch does on the backend). */
export function channelMatches(channel: string, glob: string): boolean {
  const re = new RegExp(`^${glob.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*")}$`);
  return re.test(channel);
}
