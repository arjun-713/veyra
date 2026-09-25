import Link from "next/link";
import "./PageHead.css";

interface PageHeadProps {
  trail: string;
  title: string;
  lede: string;
}

export default function PageHead({ trail, title, lede }: PageHeadProps) {
  return (
    <div className="wrap page-head">
      <p className="measure page-crumb">
        <Link href="/">Veyra</Link>
        <span aria-hidden="true"> / </span>
        <span aria-current="page">{trail}</span>
      </p>
      <h1 className="display-xl">{title}</h1>
      <p className="body-lead">{lede}</p>
    </div>
  );
}
