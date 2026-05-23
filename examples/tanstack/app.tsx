// Example: PyBridge + TanStack Query + TanStack Router
//
// Assumes you ran:
//   pybridge generate --bridge examples.basic:bridge --out src/api.ts --hooks
//
// and installed:
//   npm i @tanstack/react-query @tanstack/react-router

import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  RouterProvider,
  useNavigate,
} from "@tanstack/react-router";
import * as React from "react";

import { createClient, type AppRouter } from "./api";

// ---------------------------------------------------------------------------
// 1. Singleton client + query client
// ---------------------------------------------------------------------------

const api = createClient<AppRouter>(import.meta.env.VITE_API_URL ?? "http://localhost:8000", {
  // Per-request auth header — runs on every call
  headers: async () => ({ authorization: `Bearer ${localStorage.getItem("token") ?? ""}` }),
});

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000 } },
});

// ---------------------------------------------------------------------------
// 2. Routes
// ---------------------------------------------------------------------------

const rootRoute = createRootRoute({
  component: () => (
    <div>
      <nav style={{ display: "flex", gap: 12, padding: 12, borderBottom: "1px solid #ccc" }}>
        <Link to="/">Users</Link>
        <Link to="/ticks">Live ticks</Link>
      </nav>
      <Outlet />
    </div>
  ),
});

// --- /users  --------------------------------------------------------------
//
// Use a TanStack Router loader to prefetch the list into TanStack Query's
// cache before the route renders. Result: no spinner on first paint.

const usersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  loader: () =>
    queryClient.ensureQueryData({
      queryKey: ["users.list"],
      queryFn: () => api.users.list(),
    }),
  component: UsersPage,
});

function UsersPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: users = [] } = useQuery({
    queryKey: ["users.list"],
    queryFn: () => api.users.list(),
  });

  const createUser = useMutation({
    mutationFn: (input: { name: string; email: string }) => api.users.create(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users.list"] }),
  });

  return (
    <div style={{ padding: 16 }}>
      <h1>Users</h1>
      <ul>
        {users.map((u) => (
          <li key={u.id}>
            <Link to="/users/$id" params={{ id: u.id }}>
              {u.name} — {u.email}
            </Link>
          </li>
        ))}
      </ul>

      <button
        disabled={createUser.isPending}
        onClick={() =>
          createUser.mutate(
            { name: "New User", email: `u${Date.now()}@example.com` },
            { onSuccess: (u) => navigate({ to: "/users/$id", params: { id: u.id } }) },
          )
        }
      >
        + Add user
      </button>
    </div>
  );
}

// --- /users/$id  ----------------------------------------------------------
//
// Typed path param + per-route loader. The loader and the component share the
// same queryKey, so the component picks up the loader's cached data
// synchronously.

const userDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/users/$id",
  loader: ({ params }) =>
    queryClient.ensureQueryData({
      queryKey: ["users.get", params.id],
      queryFn: () => api.users.get({ id: params.id }),
    }),
  errorComponent: ({ error }) => {
    // PyBridge errors carry a typed `.code` field
    const code = (error as Error & { code?: string }).code;
    if (code === "NOT_FOUND") return <p>That user doesn't exist.</p>;
    return <p>Failed to load user: {String(error)}</p>;
  },
  component: UserDetail,
});

function UserDetail() {
  const { id } = userDetailRoute.useParams();
  const { data: user } = useQuery({
    queryKey: ["users.get", id],
    queryFn: () => api.users.get({ id }),
  });
  if (!user) return null;
  return (
    <div style={{ padding: 16 }}>
      <h1>{user.name}</h1>
      <p>{user.email}</p>
    </div>
  );
}

// --- /ticks  --------------------------------------------------------------
//
// Drives a WebSocket subscription from the generated client. Subscriptions
// don't need TanStack Query — they're a stream, not a cache entry.

const ticksRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/ticks",
  component: TicksPage,
});

function TicksPage() {
  const [values, setValues] = React.useState<number[]>([]);

  React.useEffect(() => {
    const sub = api.ticks.stream.subscribe();
    (async () => {
      for await (const tick of sub) {
        setValues((v) => [...v, (tick as { n: number }).n]);
      }
    })();
    return () => void sub.return();
  }, []);

  return (
    <div style={{ padding: 16 }}>
      <h1>Ticks</h1>
      <pre>{values.join(", ")}</pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3. Wire it up
// ---------------------------------------------------------------------------

const routeTree = rootRoute.addChildren([usersRoute, userDetailRoute, ticksRoute]);
const router = createRouter({ routeTree, defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
