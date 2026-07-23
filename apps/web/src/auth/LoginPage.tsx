import { LogIn, RotateCw, ShieldCheck } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { loginHref, safeReturnTo } from "@/auth/returnTo";
import { Button } from "@/components/ui/Button";
import styles from "@/auth/LoginPage.module.css";

type LoginState = "default" | "expired" | "callback_failed" | "unavailable";

const messages: Record<LoginState, { title: string; detail: string }> = {
  default: { title: "登录工作台", detail: "使用企业统一认证进入检测排程工作台。" },
  expired: { title: "登录会话已结束", detail: "请重新验证身份后继续当前工作。" },
  callback_failed: { title: "登录未完成", detail: "身份验证结果无法确认，请重新发起登录。" },
  unavailable: { title: "身份服务暂不可用", detail: "暂时无法连接身份服务，请稍后重试。" },
};

function stateFrom(value: string | null): LoginState {
  return value === "expired" || value === "callback_failed" || value === "unavailable" ? value : "default";
}

export function LoginPage() {
  const [searchParams] = useSearchParams();
  const returnTo = safeReturnTo(searchParams.get("return_to"));
  const state = stateFrom(searchParams.get("reason"));
  const message = messages[state];

  const beginLogin = () => { window.location.assign(loginHref(returnTo)); };

  return (
    <main className={styles.page} aria-labelledby="login-title">
      <section className={styles.panel}>
        <div className={styles.brand}><ShieldCheck aria-hidden="true" size={23} /><span>检测排程工作台</span></div>
        <div className={styles.copy}>
          <p className={styles.context}>检测中心 / 安全访问</p>
          <h1 id="login-title">{message.title}</h1>
          <p>{message.detail}</p>
        </div>
        <Button type="button" onClick={beginLogin}>
          {state === "unavailable" ? <RotateCw aria-hidden="true" size={17} /> : <LogIn aria-hidden="true" size={17} />}
          使用企业账号登录
        </Button>
        <p className={styles.note}>登录后将返回原来的工作页面。</p>
      </section>
    </main>
  );
}
