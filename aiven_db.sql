
CREATE TABLE workers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(100) NOT NULL UNIQUE,
  password VARCHAR(100) NOT NULL,
  role ENUM('manager', 'worker') DEFAULT 'worker',
  avatar_color VARCHAR(10) DEFAULT '#2563eb'
);

CREATE TABLE customers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL
);

CREATE TABLE locations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  customer_id INT,
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE jobs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  customer_id INT NOT NULL,
  location_id INT,
  start_time DATETIME NOT NULL,
  end_time DATETIME NOT NULL,
  status ENUM('Scheduled', 'In Progress', 'Partially Complete', 'Completed') DEFAULT 'Scheduled',
  created_by INT,
  FOREIGN KEY (customer_id) REFERENCES customers(id),
  FOREIGN KEY (location_id) REFERENCES locations(id),
  FOREIGN KEY (created_by) REFERENCES workers(id)
);

CREATE TABLE job_workers (
  job_id INT NOT NULL,
  worker_id INT NOT NULL,
  status ENUM('Pending', 'Started', 'Completed') DEFAULT 'Pending',
  PRIMARY KEY (job_id, worker_id),
  FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
  FOREIGN KEY (worker_id) REFERENCES workers(id)
);

CREATE TABLE job_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  job_id INT NOT NULL,
  action VARCHAR(200) NOT NULL,
  done_by INT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
  FOREIGN KEY (done_by) REFERENCES workers(id)
);

INSERT INTO workers (name, email, password, role, avatar_color) VALUES
('Admin Manager', 'manager@example.com', 'manager123', 'manager', '#7c3aed'),
('Priya',         'priya@example.com',   'priya123',   'worker',  '#2563eb'),
('John',          'john@example.com',    'john123',    'worker',  '#059669'),
('Kumar',         'kumar@example.com',   'kumar123',   'worker',  '#dc2626');

INSERT INTO customers (name) VALUES
('ABC Cleaning'), ('XYZ Offices'), ('Green Facilities');

INSERT INTO locations (name, customer_id) VALUES
('ABC Office', 1), ('XYZ Main', 2), ('Green HQ', 3);

INSERT INTO jobs (customer_id, location_id, start_time, end_time, status, created_by) VALUES
(1, 1, '2026-09-26 09:00:00', '2026-09-26 11:00:00', 'Completed', 1),
(2, 2, '2026-09-26 13:00:00', '2026-09-26 16:00:00', 'Completed', 1),
(3, 3, '2026-09-27 10:00:00', '2026-09-27 11:00:00', 'Scheduled', 1),
(1, 1, '2026-09-28 09:00:00', '2026-09-28 11:00:00', 'Scheduled', 1),
(2, 2, '2026-09-28 14:00:00', '2026-09-28 16:00:00', 'Scheduled', 1);

INSERT INTO job_workers (job_id, worker_id, status) VALUES
(1, 2, 'Completed'),
(2, 3, 'Completed'),
(3, 4, 'Pending'),
(4, 2, 'Pending'),
(4, 3, 'Pending'),
(5, 4, 'Pending');

INSERT INTO job_logs (job_id, action, done_by, created_at) VALUES
(1, 'Job created by Admin Manager', 1, '2026-09-25 08:00:00'),
(1, 'Job started by Priya',         2, '2026-09-26 09:05:00'),
(1, 'Job completed by Priya',       2, '2026-09-26 11:02:00'),
(2, 'Job created by Admin Manager', 1, '2026-09-25 08:05:00'),
(2, 'Job started by John',          3, '2026-09-26 13:03:00'),
(2, 'Job completed by John',        3, '2026-09-26 16:00:00'),
(3, 'Job created by Admin Manager', 1, '2026-09-25 08:10:00'),
(4, 'Job created by Admin Manager', 1, '2026-09-25 08:15:00'),
(5, 'Job created by Admin Manager', 1, '2026-09-25 08:20:00');

