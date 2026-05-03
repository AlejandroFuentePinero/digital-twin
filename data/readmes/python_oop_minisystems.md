# Python OOP Mini-Systems

**Source:** https://github.com/AlejandroFuentePinero/python-oop-mini-systems

## What it is

A suite of compact Python systems demonstrating practical object-oriented design. Each project models a real process using classes, composition, inheritance, and structured state management, with an emphasis on clarity and modularity. Designed as a learning lab to consolidate OOP fundamentals through implementation — progressing from procedural decomposition through to inheritance hierarchies and CRUD-style domain models.

Each project is implemented as an independent Jupyter notebook with supporting modules and test data where relevant.

## Project catalogue

### 01. Tic-Tac-Toe (Two-Player CLI)

Terminal-based two-player game with board rendering, input validation, win/draw detection, and a replay loop.

**Skills:** procedural programming, modular function design, control flow, input handling.

### 02. Blackjack (CLI)

Text-based Blackjack system built with classes (`Card`, `Deck`, `Hand`, `Chips`), including betting, hit/stand logic, and Ace value handling.

**Skills:** class composition, encapsulation, method structure, state management.

### 03a. Credit Card Validator

Implementation of the **Luhn algorithm** for checksum validation and card-type classification using prefix rules.

**Skills:** algorithm design, branching logic, defensive programming, string and regex handling.

### 03b. Bank Account Manager

A simplified banking system using inheritance and polymorphism. A base `Account` class is extended by `CheckingAccount`, `SavingsAccount`, and `BusinessAccount`, coordinated by a `Bank` class handling transactions.

**Skills:** inheritance, class hierarchies, polymorphism, CLI workflow.

### 03c. Product Inventory System

An inventory tracker connecting `Inventory` and `Product` classes for CRUD operations, low-stock checks, and quantity updates.

**Skills:** OOP design, list/dict structures, CRUD patterns, search/update logic.

### 03d. Library Lending System

A lending management system using an `Item` parent class for `Book`, `Journal`, and `DVD`; with `Member` and `Loan` classes managing lending, returns, and due dates.

**Skills:** inheritance, encapsulation, state management, domain modelling.

## Key engineering decisions

- **Progression from procedural (Tic-Tac-Toe) to OOP (Blackjack) to inheritance (Bank, Library).** The catalogue is sequenced so each project introduces one new design dimension on top of mastered fundamentals — avoids dropping the learner into deep-class-hierarchy land before composition is solid.
- **Domain modelling as the central skill, not syntax memorisation.** Each system maps a real process (a game, a banking workflow, a library) into class structure. The OOP machinery is incidental; the design judgment about which entities deserve classes vs methods vs functions is the actual lesson.
- **CRUD patterns + state management treated as core domains.** The Inventory and Library systems demonstrate the boring-but-fundamental shape of most production code — entities with create/read/update/delete operations, persistent state, search/update logic. This is the shape of real backend work.
- **Self-contained notebooks per project.** No cross-project dependencies; each notebook is a complete walkthrough of problem, design, and implementation.

## Learning outcomes

- Application of OOP principles: composition, inheritance, encapsulation, polymorphism
- Structured modelling of real processes using class hierarchies
- Implementation of algorithms and CRUD workflows with core Python data structures
- Strengthened debugging, validation, and modular design techniques
- Creation of reusable, well-documented code components

## Stack

Python 3 · `datetime` · `re` · `sys` · `os` · Jupyter
