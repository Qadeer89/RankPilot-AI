"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, verifyEmail } from "@/lib/api";
import styles from "../form.module.css";

function VerifyEmail() {
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<"working" | "done" | "failed">(token ? "working" : "failed");
  const [message, setMessage] = useState<string>(token ? "" : "This link is missing its verification token.");

  useEffect(() => {
    if (!token) return;
    verifyEmail(token)
      .then((result) => {
        setMessage(result.message);
        setState("done");
      })
      .catch((err) => {
        setMessage(err instanceof ApiError ? err.message : "Something went wrong.");
        setState("failed");
      });
  }, [token]);

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <h1>Verify email</h1>
        {state === "working" && <p role="status">Verifying your email address…</p>}
        {state === "done" && <p role="status">{message}</p>}
        {state === "failed" && (
          <p className={styles.error} role="alert">
            {message}
          </p>
        )}
        <p className={styles.footerLink}>
          <Link href="/dashboard">Go to your dashboard</Link>
        </p>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmail />
    </Suspense>
  );
}
