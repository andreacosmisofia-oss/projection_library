import { useHealth } from '@/api/useHealth'
import { useProjects } from '@/api/useProjects'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

export function ProjectsListPage() {
  const health = useHealth()
  const projects = useProjects()

  const backendOk = health.data?.status === 'ok'

  return (
    <div className="container mx-auto max-w-5xl py-10 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Projection Library
          </h1>
          <p className="text-sm text-muted-foreground">
            {health.isLoading
              ? 'Checking backend…'
              : backendOk
                ? 'Backend connected'
                : 'Backend unreachable'}
          </p>
        </div>
        <Button disabled>+ New project</Button>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Projects</CardTitle>
          <CardDescription>
            {projects.isLoading
              ? 'Loading…'
              : projects.isError
                ? 'Failed to load projects.'
                : `${projects.data?.count ?? 0} project(s)`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {projects.data && projects.data.items.length > 0 ? (
            <ul className="divide-y">
              {projects.data.items.map((p) => (
                <li
                  key={p.id}
                  className="flex items-center justify-between py-3"
                >
                  <div>
                    <div className="font-medium">{p.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {p.sector_pack} · {p.currency} · {p.horizon_years}y
                    </div>
                  </div>
                  <code className="text-xs text-muted-foreground">{p.id}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              No projects yet. Create one to get started.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
