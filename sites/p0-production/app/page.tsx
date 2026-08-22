import type { Metadata } from "next";
import P0Client from "./P0Client";

export const metadata: Metadata = {
  title: "Стратегия — MOX-ADV",
  description:
    "Рабочий кандидат стратегии и безопасного создания кампании на реальных данных Директа, Метрики и сайта.",
};

export default function Home() {
  return <P0Client />;
}
