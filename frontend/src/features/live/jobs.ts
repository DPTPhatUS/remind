import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { conversationStatus } from "./state";

type Job = { id: string; status: string };

export function useConversationJobs(onError: (message: string) => void) {
  const [jobsStatus, setJobsStatus] = useState("");
  const [hasFailedJobs, setHasFailedJobs] = useState(false);

  useEffect(() => {
    let active = true;
    let poll = 0;
    async function pollJobs() {
      try {
        const jobs = await api<Job[]>("/jobs");
        if (!active) return;
        const status = conversationStatus(jobs);
        setHasFailedJobs(status.hasFailedJobs);
        setJobsStatus(status.jobsStatus);
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

  const retryJobs = async () => {
    try {
      const jobs = await api<Job[]>("/jobs");
      for (const job of jobs.filter((job) => job.status === "failed"))
        await api(`/jobs/${job.id}/retry`, { method: "POST" });
      setJobsStatus("Retrying failed conversations.");
    } catch (error) {
      onError(String(error));
    }
  };

  return { jobsStatus, hasFailedJobs, retryJobs };
}
