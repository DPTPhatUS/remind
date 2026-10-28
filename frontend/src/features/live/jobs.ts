import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { conversationStatus } from "./state";

type Job = { status: string };

export function useConversationJobs() {
  const [jobsStatus, setJobsStatus] = useState("");

  useEffect(() => {
    let active = true;
    let poll = 0;
    async function pollJobs() {
      try {
        const jobs = await api<Job[]>("/jobs");
        if (!active) return;
        setJobsStatus(conversationStatus(jobs));
      } catch {
        if (active) {
          setJobsStatus(
            "Conversation processing status is unavailable. Check the server connection.",
          );
        }
      } finally {
        if (active) {
          poll = window.setTimeout(() => void pollJobs(), 3000);
        }
      }
    }
    void pollJobs();
    return () => {
      active = false;
      clearTimeout(poll);
    };
  }, []);

  return jobsStatus;
}
