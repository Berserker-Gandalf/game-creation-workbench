export default function Logo({ className = '' }: { className?: string }) {
  return <img className={'studio-logo ' + className} src="/brand/mark.svg" width="48" height="48" alt="" aria-hidden="true"/>;
}
