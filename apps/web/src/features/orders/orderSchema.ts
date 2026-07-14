import { z } from "zod";

export const orderSchema = z.object({
  sample_name: z.string().trim().min(1, "请输入样品名称"),
  sample_quantity: z.coerce.number().int().min(1, "样品数量必须大于 0"),
  certification_type: z.string().min(1, "请选择认证类型"),
  priority: z.enum(["normal", "urgent", "vip"]),
  promised_finish_time: z.string().min(1, "请选择承诺完成时间"),
  project_ids: z.array(z.string()).min(1, "至少选择一个检测项目"),
});
export type OrderFormValues = z.infer<typeof orderSchema>;

export const orderPatchSchema = orderSchema.pick({ priority: true, promised_finish_time: true, project_ids: true });
export type OrderPatchFormValues = z.infer<typeof orderPatchSchema>;

export const retestSchema = z.object({
  reason: z.string().trim().min(1, "请输入复测原因"),
});
export type RetestFormValues = z.infer<typeof retestSchema>;
