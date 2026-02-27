class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/35/6e/ebafc9688b5dbe0fa9dd4194263e89be78287ce8bcd8a93a5dda7b65ca81/agentops_mcp_server-0.0.12.tar.gz"
  sha256 "4b8ff2130cce48ca3698a5c32b1b177de360164ef0d1a95b1c6e37b4783c3ea8"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
