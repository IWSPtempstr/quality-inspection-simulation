export type ProblemDetails = { type?: string; title?: string; status: number; detail?: string; instance?: string };

export class ApiProblem extends Error {
  constructor(public readonly problem: ProblemDetails) { super(problem.detail ?? problem.title ?? "请求失败"); }
  get isConflict() { return this.problem.status === 409; }
  get isDegraded() { return this.problem.status === 503; }
  get isPermissionDenied() { return this.problem.status === 403; }
}
