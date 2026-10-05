-- Iconiq Hair & Beauty: booking database.
-- Run this once in Supabase: Dashboard -> SQL Editor -> New query -> paste -> Run.
-- Safe to run again; it only creates what is missing.
--
-- Only the website server (using the service_role key) can read or write these
-- tables. Row Level Security is on with no public policies, so the public
-- anon key cannot see customer names or phone numbers.

create table if not exists public.bookings (
  id          bigint generated always as identity primary key,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  date        date not null,
  time        text not null,
  service     text not null,
  stylist     text,
  first_name  text not null,
  last_name   text not null default '',
  email       text not null default '',
  phone       text not null,
  notes       text not null default '',
  status      text not null default 'confirmed'
              check (status in ('confirmed', 'completed', 'no_show', 'cancelled')),
  source      text not null default 'website' check (source in ('website', 'admin'))
);
create index if not exists bookings_slot_idx on public.bookings (date, time);
create index if not exists bookings_created_idx on public.bookings (created_at);

create table if not exists public.blocks (
  id      bigint generated always as identity primary key,
  date    date not null,
  time    text,            -- null closes the whole day
  reason  text not null default ''
);
create index if not exists blocks_date_idx on public.blocks (date);

create table if not exists public.settings (
  key    text primary key,
  value  text not null
);

create table if not exists public.admin_sessions (
  token    text primary key,
  csrf     text not null,
  expires  timestamptz not null
);

alter table public.bookings       enable row level security;
alter table public.blocks         enable row level security;
alter table public.settings       enable row level security;
alter table public.admin_sessions enable row level security;
revoke all on public.bookings, public.blocks, public.settings, public.admin_sessions from anon, authenticated;

insert into public.settings (key, value) values ('capacity', '2') on conflict (key) do nothing;

-- Books a slot atomically. A per-slot lock makes simultaneous requests queue up,
-- so the capacity check and insert can't race. Raises SLOT_FULL when full or blocked.
create or replace function public.book_appointment(p jsonb)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
  v_date date := (p->>'date')::date;
  v_time text := p->>'time';
  v_cap  int  := coalesce((select value::int from settings where key = 'capacity'), 2);
  v_id   bigint;
begin
  perform pg_advisory_xact_lock(hashtext(v_date::text || ' ' || v_time));

  if exists (select 1 from blocks where date = v_date and (time is null or time = v_time)) then
    raise exception 'SLOT_FULL';
  end if;
  if (select count(*) from bookings
      where date = v_date and time = v_time and status <> 'cancelled') >= v_cap then
    raise exception 'SLOT_FULL';
  end if;

  insert into bookings (date, time, service, stylist, first_name, last_name, email, phone, notes, source)
  values (v_date, v_time, p->>'service', p->>'stylist', p->>'first_name',
          coalesce(p->>'last_name', ''), coalesce(p->>'email', ''), p->>'phone',
          coalesce(p->>'notes', ''), coalesce(p->>'source', 'website'))
  returning id into v_id;
  return v_id;
end;
$$;

-- Changes a booking's status. Restoring a cancelled booking re-checks capacity
-- under the same lock. Returns null on success, or an error code.
create or replace function public.set_booking_status(p_id bigint, p_status text)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  b     bookings;
  v_cap int := coalesce((select value::int from settings where key = 'capacity'), 2);
begin
  select * into b from bookings where id = p_id;
  if not found then
    return 'NOT_FOUND';
  end if;
  perform pg_advisory_xact_lock(hashtext(b.date::text || ' ' || b.time));
  if b.status = 'cancelled' and p_status <> 'cancelled' then
    if (select count(*) from bookings
        where date = b.date and time = b.time and status <> 'cancelled') >= v_cap then
      return 'SLOT_FULL';
    end if;
  end if;
  update bookings set status = p_status, updated_at = now() where id = p_id;
  return null;
end;
$$;

revoke all on function public.book_appointment(jsonb) from public, anon, authenticated;
revoke all on function public.set_booking_status(bigint, text) from public, anon, authenticated;
grant execute on function public.book_appointment(jsonb) to service_role;
grant execute on function public.set_booking_status(bigint, text) to service_role;

-- Course certificates. The admin panel issues them; the public Verify
-- Certificate page looks one up by its reference number (through the server,
-- which only returns the fields printed on the certificate).
create table if not exists public.certificates (
  id            bigint generated always as identity primary key,
  created_at    timestamptz not null default now(),
  ref           text not null unique,
  student_name  text not null,
  course        text not null,
  duration      text not null default '',
  completed_on  date not null,
  revoked       boolean not null default false
);
alter table public.certificates enable row level security;
revoke all on public.certificates from anon, authenticated;
