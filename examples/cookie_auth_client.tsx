// Client for examples/cookie_auth.py
//
// Generate the typed client first:
//   pybridge generate --bridge examples.cookie_auth:bridge --out src/api.ts
//
// Two flags do all the work:
//   credentials: "include"   -> browser sends/receives cookies cross-origin
//   csrfCookie:  "pyb_csrf"  -> client reads the CSRF cookie and echoes it
//                               in X-CSRF-Token on every request
//
// The session cookie (pyb_session) is HttpOnly — JS never touches it; the
// browser attaches it automatically because credentials: "include" is set.

import { createClient, type AppRouter } from "./api";

export const api = createClient<AppRouter>(
  import.meta.env.VITE_API_URL ?? "http://localhost:8000",
  {
    credentials: "include",
    csrfCookie: "pyb_csrf",
  },
);

// ---------------------------------------------------------------------------
// Usage
// ---------------------------------------------------------------------------

export async function signInFlow() {
  try {
    const me = await api.auth.me();
    console.log("already signed in as", me.name);
    return me;
  } catch (err) {
    if ((err as Error & { code?: string }).code !== "UNAUTHORIZED") throw err;
  }

  // Cookie set on this response; subsequent calls send it automatically.
  const user = await api.auth.login({ email: "alice@example.com", password: "hunter2" });
  console.log("signed in as", user.name);
  return user;
}

export async function workWithNotes() {
  await signInFlow();
  const note = await api.notes.create({ text: "hello from a typed RPC call" });
  console.log("created", note.id);
  const all = await api.notes.list();
  console.log("have", all.length, "notes");
}

export async function signOut() {
  await api.auth.logout();
  // Future calls to api.auth.me() now throw UNAUTHORIZED.
}

// ---------------------------------------------------------------------------
// React hook example (TanStack Query)
// ---------------------------------------------------------------------------

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export function useCurrentUser() {
  return useQuery({
    queryKey: ["auth.me"],
    queryFn: () => api.auth.me(),
    retry: (_n, err) => (err as Error & { code?: string }).code !== "UNAUTHORIZED",
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { email: string; password: string }) => api.auth.login(input),
    onSuccess: (user) => qc.setQueryData(["auth.me"], user),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.auth.logout(),
    onSuccess: () => qc.removeQueries({ queryKey: ["auth.me"] }),
  });
}
