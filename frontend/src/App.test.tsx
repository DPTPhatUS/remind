import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import App from "./App";
it("starts with the camera off and explicit capture controls", () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  expect(screen.getByRole("button", { name: "Start camera" })).toBeEnabled();
  expect(screen.getByRole("link", { name: "People" })).toHaveAttribute(
    "href",
    "/people",
  );
});
