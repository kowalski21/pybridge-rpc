# Example: TanStack Router + TanStack Query

PyBridge composes cleanly with the TanStack ecosystem. Below is a real-world setup with typed route loaders, query-cache prefetching, mutations, and a WebSocket subscription — all from the generated client.

> Full file: [`examples/tanstack/app.tsx`](../examples/tanstack/app.tsx)

```ts
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createRootRoute, createRoute, createRouter,
  Link, Outlet, RouterProvider, useNavigate,
} from "@tanstack/react-router";
import * as React from "react";

import { createClient, type AppRouter } from "./api";

// 1. Singleton typed client. AppRouter is generated from your Python bridge.
const api = createClient<AppRouter>(import.meta.env.VITE_API_URL ?? "http://localhost:8000", {
  headers: async () => ({ authorization: `Bearer ${localStorage.getItem("token") ?? ""}` }),
});

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });

// 2. Root layout
const rootRoute = createRootRoute({
  component: () => (
    <div>
      <nav><Link to="/">Users</Link> · <Link to="/ticks">Live ticks</Link></nav>
      <Outlet />
    </div>
  ),
});

// 3. /users — loader prefetches into the query cache, component picks it up sync.
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
    <div>
      <ul>
        {users.map((u) => (
          <li key={u.id}>
            <Link to="/users/$id" params={{ id: u.id }}>{u.name} — {u.email}</Link>
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
      >+ Add user</button>
    </div>
  );
}

// 4. /users/$id — typed path param + per-route loader + typed error handling.
const userDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/users/$id",
  loader: ({ params }) =>
    queryClient.ensureQueryData({
      queryKey: ["users.get", params.id],
      queryFn: () => api.users.get({ id: params.id }),
    }),
  errorComponent: ({ error }) => {
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
  return <div><h1>{user.name}</h1><p>{user.email}</p></div>;
}

// 5. /ticks — drives a WebSocket subscription as a native async iterator.
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
  return <pre>{values.join(", ")}</pre>;
}

// 6. Wire it up
const routeTree = rootRoute.addChildren([usersRoute, userDetailRoute, ticksRoute]);
const router = createRouter({ routeTree, defaultPreload: "intent" });
declare module "@tanstack/react-router" {
  interface Register { router: typeof router }
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
```

## What this gets you

- **Typed end-to-end**: route params → query function → procedure call → response. A field rename in `User` (Python) is a compile error in `UserDetail.tsx`.
- **No spinner on first paint**: route loaders prefetch into TanStack Query's cache; the component renders synchronously with cached data.
- **Typed error handling**: `ProcedureError(code="NOT_FOUND", ...)` raised in Python shows up as `error.code === "NOT_FOUND"` in `errorComponent`.
- **Subscriptions are async iterators**: `for await (const tick of sub)` — drop straight into a `useEffect`.
- **File uploads with no API change**: pass a `File` and the generated client switches to `FormData` automatically.

## Generating the client

```bash
pybridge generate --bridge server:bridge --out src/api.ts --hooks --watch
```

`--watch` regenerates on save; `--hooks` adds a `createHooks(client)` helper with typed `useQuery` / `useMutation` wrappers if you'd rather skip the explicit `queryKey` boilerplate.

`pybridge openapi --bridge server:bridge --out openapi.json` exports a standalone OpenAPI 3.0 spec — useful for non-TypeScript consumers or for piping into other tools.
